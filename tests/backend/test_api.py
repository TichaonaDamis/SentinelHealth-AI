from tests.backend.conftest import AS_OF

API = "/api/v1"


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_login_rejects_bad_password(client):
    r = await client.post(f"{API}/auth/token", data={"username": "admin@sentinelhealth.dev", "password": "nope"})
    assert r.status_code == 401


async def test_requires_auth(client):
    assert (await client.get(f"{API}/diseases")).status_code == 401


async def test_me(client, epi):
    r = await client.get(f"{API}/auth/me", headers=epi)
    assert r.json()["role"] == "epidemiologist"


async def test_rbac_viewer_cannot_scan(client, viewer):
    r = await client.post(f"{API}/analytics/scan", json={}, headers=viewer)
    assert r.status_code == 403


async def test_rbac_partner_cannot_read_linelist(client, partner):
    r = await client.get(f"{API}/analytics/hotspots", params={"disease": "INFLUENZA"}, headers=partner)
    assert r.status_code == 403


async def test_jurisdiction_scoping(client, tx_officer):
    r = await client.get(f"{API}/regions", headers=tx_officer)
    assert r.status_code == 200
    assert {x["state"] for x in r.json()} == {"TX"}
    r = await client.get(f"{API}/regions", params={"state": "NY"}, headers=tx_officer)
    assert r.status_code == 403


async def test_risk_assessment(client, epi):
    r = await client.get(f"{API}/analytics/risk", params={"as_of": str(AS_OF)}, headers=epi)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 30  # 10 regions x 3 diseases
    for row in rows:
        assert row["risk_level"] in {"green", "yellow", "orange", "red"}
        assert 0 <= row["outbreak_probability"] <= 1
        assert row["outbreak_tier"] in {"High", "Medium", "Low"}
        assert row["reasons"]


async def test_scan_creates_events_and_deduplicates_alerts(client, epi):
    body = {"as_of": str(AS_OF), "notify": True}
    r1 = (await client.post(f"{API}/analytics/scan", json=body, headers=epi)).json()
    assert r1["evaluated"] == 30
    assert r1["alerts_created"] >= 1
    r2 = (await client.post(f"{API}/analytics/scan", json=body, headers=epi)).json()
    assert r2["alerts_created"] == 0, "same-level alerts must be de-duplicated"
    alerts = (await client.get(f"{API}/alerts", headers=epi)).json()
    assert len(alerts) == r1["alerts_created"]
    for a in alerts:
        assert a["risk_level"] in {"yellow", "orange", "red"}
        assert "Why:" in a["message"]
        assert any(d["channel"] == "log" for d in a["deliveries"])


async def test_alert_acknowledge(client, epi, viewer):
    alerts = (await client.get(f"{API}/alerts", headers=epi)).json()
    if not alerts:
        return
    aid = alerts[0]["id"]
    assert (await client.patch(f"{API}/alerts/{aid}", json={"status": "acknowledged"}, headers=viewer)).status_code == 403
    r = await client.patch(f"{API}/alerts/{aid}", json={"status": "acknowledged", "note": "triaged"}, headers=epi)
    assert r.status_code == 200
    assert r.json()["acknowledged_by"] == "epi@sentinelhealth.dev"


async def test_forecast(client, epi):
    r = await client.get(f"{API}/forecasts/INFLUENZA/36061", params={"as_of": str(AS_OF)}, headers=epi)
    assert r.status_code == 200, r.text
    fc = r.json()
    assert [h["horizon_days"] for h in fc["horizons"]] == [7, 14, 30]
    assert len(fc["path"]) == 30
    for p in fc["path"]:
        assert p["lower"] <= p["mean"] + 1e-6 and p["mean"] <= p["upper"] + 1e-6
    assert fc["horizons"][0]["hospitalization_risk"] in {"low", "moderate", "high", "very_high"}


async def test_hotspots(client, epi):
    r = await client.get(f"{API}/analytics/hotspots", params={"disease": "INFLUENZA", "method": "dbscan"}, headers=epi)
    assert r.status_code == 200
    for h in r.json():
        assert h["case_count"] >= 15


async def test_dashboard(client, viewer):
    r = await client.get(f"{API}/dashboard/summary", headers=viewer)
    assert r.status_code == 200
    d = r.json()
    assert d["kpis"]["active_cases"] > 0
    assert len(d["regions"]) == 25  # all reference regions are on the map
    assert d["trend"]


async def test_ingest_with_lineage(client, partner, admin):
    rec = {"observed_on": str(AS_OF), "region_id": "48201", "disease_code": "INFLUENZA", "ed_visits": 999}
    r = await client.post(f"{API}/surveillance/signals",
                          json={"source": "hospital_feed", "pipeline_run_id": "run-1", "records": [
                              rec, {**rec, "region_id": "36061"}]}, headers=partner)
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["accepted"] == 1 and res["rejected"] == 1  # NY is outside the TX partner's jurisdiction
    lin = await client.get(f"{API}/lineage/signal", headers=admin,
                           params={"disease": "INFLUENZA", "region_id": "48201", "observed_on": str(AS_OF)})
    assert lin.status_code == 200
    assert lin.json()["id"] == res["batch_id"]
    assert lin.json()["submitted_by"] == "partner@sentinelhealth.dev"


async def test_case_report_patient_ref_encrypted_at_rest(client, partner):
    r = await client.post(f"{API}/surveillance/cases", headers=partner, json=[{
        "disease_code": "MEASLES", "region_id": "48201", "onset_date": str(AS_OF), "patient_ref": "PSEUDO-123"}])
    assert r.status_code == 201
    from sqlalchemy import text

    from app.db.session import get_engine

    async with get_engine().connect() as conn:
        raw = (await conn.execute(text("select patient_ref from case_reports where patient_ref is not null"))).scalar()
    assert raw and "PSEUDO-123" not in raw


async def test_copilot_offline_answer_with_citations(client, epi):
    r = await client.post(f"{API}/copilot/ask", headers=epi,
                          json={"question": "What should we do about a measles exposure?", "disease_code": "MEASLES"})
    assert r.status_code == 200
    a = r.json()
    assert a["provider"] == "offline"
    assert a["citations"] and a["citations"][0]["title"].startswith("Measles")
    assert any("Data current through" in f for f in a["context_facts"])


async def test_copilot_sitrep(client, tx_officer):
    r = await client.post(f"{API}/copilot/sitrep", headers=tx_officer, json={"period_days": 14})
    assert r.status_code == 200
    assert "Summary" in r.json()["answer"]


async def test_audit_log_records_access_and_denials(client, admin):
    r = await client.get(f"{API}/admin/audit-logs", params={"limit": 1000}, headers=admin)
    assert r.status_code == 200
    actions = {row["action"] for row in r.json()}
    assert "auth:login" in actions
    assert "auth:login_failed" in actions
    assert any(a.startswith("denied:") for a in actions)
    assert "surveillance:ingest" in actions


async def test_admin_creates_user_with_password_policy(client, admin):
    weak = {"email": "new.epi@dshs.texas.gov", "full_name": "New Epi", "password": "short", "role": "epidemiologist"}
    assert (await client.post(f"{API}/auth/users", json=weak, headers=admin)).status_code == 422
    ok = {**weak, "password": "Correct-Horse-9-Battery", "jurisdiction": "tx"}
    r = await client.post(f"{API}/auth/users", json=ok, headers=admin)
    assert r.status_code == 201
    assert r.json()["jurisdiction"] == "TX"


async def test_model_evaluation(client, epi, viewer):
    assert (await client.get(f"{API}/admin/model-evaluation", headers=viewer)).status_code == 403
    r = await client.get(f"{API}/admin/model-evaluation", headers=epi)
    assert r.status_code == 200
    m = r.json()
    assert {"accuracy", "precision", "recall", "f1", "roc_auc", "confusion_matrix", "roc_curve"} <= set(m["classifier"])
