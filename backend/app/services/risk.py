"""Public-health risk level model (Green / Yellow / Orange / Red).

The level combines the calibrated outbreak probability, the anomaly signal,
growth, disease severity and forecast hospital burden into a 0-100 score.
Rules are deliberately transparent so epidemiologists can audit why a level
was assigned; every assessment carries human-readable ``reasons``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LEVELS = ("green", "yellow", "orange", "red")
LEVEL_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}
SCORE_BANDS = (25.0, 50.0, 75.0)  # score >= band -> next level


@dataclass
class RiskInputs:
    outbreak_probability: float
    anomaly_score: float  # 0..1 percentile-like
    anomaly_flag: bool
    growth_7d: float  # ratio of this week's to last week's 7-day average
    severity_weight: float = 1.0
    hospitalization_risk: str | None = None  # low|moderate|high|very_high
    ears_c2: float = 0.0


@dataclass
class RiskAssessment:
    level: str
    score: float
    reasons: list[str] = field(default_factory=list)


def assess_risk(x: RiskInputs) -> RiskAssessment:
    reasons: list[str] = []
    score = 55.0 * x.outbreak_probability
    if x.outbreak_probability >= 0.6:
        reasons.append(f"High outbreak likelihood ({x.outbreak_probability:.0%})")
    elif x.outbreak_probability >= 0.3:
        reasons.append(f"Elevated outbreak likelihood ({x.outbreak_probability:.0%})")

    if x.anomaly_flag:
        score += 15.0 * min(1.0, x.anomaly_score)
        reasons.append("Multi-source anomaly detected (syndromic/lab/wastewater)")
    if x.ears_c2 >= 3.0:
        score += 5.0
        reasons.append(f"EARS C2 aberration (C2={x.ears_c2:.1f})")

    if x.growth_7d >= 1.5:
        score += 15.0
        reasons.append(f"Rapid growth: cases ×{x.growth_7d:.1f} week-over-week")
    elif x.growth_7d >= 1.2:
        score += 8.0
        reasons.append(f"Increasing trend: cases ×{x.growth_7d:.2f} week-over-week")

    hosp_bonus = {"high": 8.0, "very_high": 15.0}.get(x.hospitalization_risk or "", 0.0)
    if hosp_bonus:
        score += hosp_bonus
        reasons.append(f"Forecast hospitalization burden {x.hospitalization_risk.replace('_', ' ')}")

    score = min(100.0, score * x.severity_weight)
    if x.severity_weight > 1.0 and score >= SCORE_BANDS[0]:
        reasons.append("High-consequence disease (severity weighting applied)")

    level = LEVELS[sum(score >= b for b in SCORE_BANDS)]
    # Guard rails: never green when the classifier is confident; never red on a single weak signal.
    if x.outbreak_probability >= 0.6 and LEVEL_RANK[level] < LEVEL_RANK["orange"]:
        level = "orange"
    elif x.outbreak_probability >= 0.3 and level == "green":
        level = "yellow"
    if level == "red" and x.outbreak_probability < 0.5:
        level = "orange"
    if not reasons:
        reasons.append("Activity within expected seasonal range")
    return RiskAssessment(level=level, score=round(score, 1), reasons=reasons)


def escalates(previous: str | None, new: str) -> bool:
    return previous is None or LEVEL_RANK[new] > LEVEL_RANK[previous]
