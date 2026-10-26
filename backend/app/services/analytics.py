"""Surveillance scan: features -> anomaly + outbreak probability -> risk level -> events and alerts."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, CaseReport, Disease, OutbreakEvent, Region
from app.schemas import Contribution, RiskAssessmentOut
from app.services.data_access import latest_signal_date, load_panel
from app.services.ml_runtime import get_runtime
from app.services.notifications import AUDIENCES_BY_LEVEL, AlertMessage, dispatch
from app.services.risk import LEVEL_RANK, RiskInputs, assess_risk, escalates
from sentinel_ml.anomaly.detectors import ears_c2
from sentinel_ml.classification import risk_tier
from sentinel_ml.features import build_features
from sentinel_ml.spatial import detect_hotspots

log = logging.getLogger(__name__)
LOOKBACK_DAYS = 90


async def assess(
    db: AsyncSession, as_of: date | None = None, diseases: list[str] | None = None, state: str | None = None
) -> list[RiskAssessmentOut]:
    as_of = as_of or await latest_signal_date(db)
    if as_of is None:
        return []
    # Neighbour features need the national panel even for a state-scoped user; results are filtered after.
    panel = await load_panel(db, end=as_of, days=LOOKBACK_DAYS, diseases=diseases)
    if panel.empty:
        return []
    feats = build_features(panel)
    feats["ears_c2"] = feats.groupby(["disease", "region_id"])["cases"].transform(ears_c2)
    latest = feats[feats["date"] == pd.Timestamp(as_of)].reset_index(drop=True)
    if state:
        latest = latest[latest["state"] == state].reset_index(drop=True)
    if latest.empty:
        return []

    rt = get_runtime()
    proba, drivers, _ = rt.outbreak_probability(latest)
    scores, flags, _ = rt.anomaly_scores(latest)
    severity = {d.code: d.severity_weight for d in (await db.scalars(select(Disease))).all()}

    out: list[RiskAssessmentOut] = []
    for i, row in latest.iterrows():
        growth = float(row.get("cases_growth_7") or 1.0)
        ra = assess_risk(RiskInputs(
            outbreak_probability=float(proba[i]), anomaly_score=float(scores[i]), anomaly_flag=bool(flags[i]),
            growth_7d=growth, severity_weight=severity.get(row["disease"], 1.0), ears_c2=float(row["ears_c2"]),
        ))
        out.append(RiskAssessmentOut(
            disease_code=row["disease"], region_id=row["region_id"], region_name=row["region_name"],
            state=row["state"], as_of=as_of, risk_level=ra.level, risk_score=ra.score,
            outbreak_probability=round(float(proba[i]), 4), outbreak_tier=risk_tier(float(proba[i])),
            anomaly_score=round(float(scores[i]), 4), anomaly_flag=bool(flags[i]),
            ears_c2=round(float(row["ears_c2"]), 2),
            incidence_7d_per_100k=round(float(row["incidence_7d_per_100k"] or 0.0), 2),
            growth_7d=round(growth, 3),
            drivers=[Contribution(feature=f, value=v) for f, v in drivers[i]],
            reasons=ra.reasons,
        ))
    return sorted(out, key=lambda a: (-LEVEL_RANK[a.risk_level], -a.risk_score))


async def scan_and_alert(
    db: AsyncSession, as_of: date | None = None, diseases: list[str] | None = None,
    state: str | None = None, notify: bool = True, method: str | None = None,
) -> tuple[list[RiskAssessmentOut], int]:
    """Assess all series, persist outbreak events for non-green signals and raise de-duplicated alerts."""
    assessments = await assess(db, as_of, diseases, state)
    signals = [a for a in assessments if a.risk_level != "green"]
    if not signals:
        return assessments, 0
    rt = get_runtime()
    method = method or ("ml_ensemble" if rt.classifier is not None else "heuristic+ears")
    regions = {r.id: r for r in (await db.scalars(select(Region))).all()}
    diseases_by_code = {d.code: d for d in (await db.scalars(select(Disease))).all()}
    cutoff = datetime.now(UTC) - timedelta(days=7)

    created = 0
    for a in signals:
        prev = await db.scalar(
            select(Alert).where(Alert.disease_code == a.disease_code, Alert.region_id == a.region_id,
                                Alert.status.in_(["open", "acknowledged"]), Alert.created_at >= cutoff)
            .order_by(Alert.created_at.desc()).limit(1)
        )
        event = OutbreakEvent(
            disease_code=a.disease_code, region_id=a.region_id, detected_on=a.as_of, risk_level=a.risk_level,
            risk_score=a.risk_score, outbreak_probability=a.outbreak_probability, anomaly_score=a.anomaly_score,
            method=method, explanation={"reasons": a.reasons, "drivers": [d.model_dump() for d in a.drivers],
                                        "ears_c2": a.ears_c2, "growth_7d": a.growth_7d},
        )
        db.add(event)
        if prev is not None and not escalates(prev.risk_level, a.risk_level):
            continue  # same or lower level already alerted this week: no alert fatigue
        await db.flush()
        disease = diseases_by_code.get(a.disease_code)
        region = regions[a.region_id]
        audiences = AUDIENCES_BY_LEVEL[a.risk_level]
        title = f"{a.risk_level.capitalize()} alert: {disease.name if disease else a.disease_code} in {region.name}, {region.state}"
        body = (
            f"As of {a.as_of:%Y-%m-%d}: outbreak likelihood {a.outbreak_probability:.0%} ({a.outbreak_tier}), "
            f"7-day incidence {a.incidence_7d_per_100k:.1f}/100k, week-over-week growth ×{a.growth_7d:.2f}.\n"
            "Why: " + "; ".join(a.reasons) + ".\n"
            "Top drivers: " + ", ".join(f"{d.feature} ({d.value:+.2f})" for d in a.drivers[:3]) + "."
        )
        alert = Alert(outbreak_event_id=event.id, disease_code=a.disease_code, region_id=a.region_id,
                      risk_level=a.risk_level, title=title, message=body, audiences=audiences, deliveries=[])
        db.add(alert)
        await db.flush()
        if notify and audiences:
            alert.deliveries = await dispatch(AlertMessage(
                alert_id=str(alert.id), level=a.risk_level, title=title, body=body, disease=a.disease_code,
                region_id=a.region_id, state=region.state, audiences=audiences))
        created += 1
    await db.commit()
    return assessments, created


async def hotspots(
    db: AsyncSession, disease: str, window_days: int = 21, baseline_days: int = 84,
    state: str | None = None, method: str = "hdbscan", min_samples: int = 15,
) -> list[dict]:
    end = await db.scalar(select(CaseReport.onset_date).where(CaseReport.disease_code == disease)
                          .order_by(CaseReport.onset_date.desc()).limit(1))
    if end is None:
        return []
    start = end - timedelta(days=window_days + baseline_days)
    stmt = select(CaseReport.onset_date, CaseReport.lat, CaseReport.lon).where(
        CaseReport.disease_code == disease, CaseReport.onset_date > start, CaseReport.lat.is_not(None))
    if state:
        stmt = stmt.join(Region, Region.id == CaseReport.region_id).where(Region.state == state)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []
    pts = pd.DataFrame(rows, columns=["date", "lat", "lon"]).assign(disease=disease)
    cut = end - timedelta(days=window_days)
    cur, base = pts[pts["date"] > cut], pts[pts["date"] <= cut]
    if len(cur) > 3000:  # bound clustering cost; keep sampling rate equal across windows
        frac = 3000 / len(cur)
        cur = cur.sample(frac=frac, random_state=0)
        base = base.sample(frac=frac, random_state=0)
    found = detect_hotspots(cur, base, method=method, min_samples=min_samples,
                            window_ratio=baseline_days / window_days)
    return [h.as_dict() for h in found]


def downsample_series(values: np.ndarray, max_points: int = 400) -> np.ndarray:
    if len(values) <= max_points:
        return values
    idx = np.linspace(0, len(values) - 1, max_points).astype(int)
    return values[idx]
