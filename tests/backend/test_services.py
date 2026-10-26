import numpy as np
import pytest

from app.core.rbac import Perm, has_permission, jurisdiction_filter
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.services.copilot.embeddings import HashingEmbedder
from app.services.copilot.llm import scrub_phi
from app.services.copilot.retriever import bm25_scores, chunk_text, rrf
from app.services.notifications import AlertMessage, dispatch
from app.services.risk import RiskInputs, assess_risk, escalates


def test_password_hashing():
    h = hash_password("S3cure-passphrase!")
    assert verify_password("S3cure-passphrase!", h)
    assert not verify_password("wrong", h)
    assert h != hash_password("S3cure-passphrase!")  # salted


def test_jwt_roundtrip():
    token, _ = create_access_token("user-1", "epidemiologist", "TX")
    claims = decode_access_token(token)
    assert claims["sub"] == "user-1" and claims["jur"] == "TX"


def test_rbac_matrix():
    assert has_permission("admin", Perm.READ_AUDIT)
    assert not has_permission("viewer", Perm.USE_COPILOT)
    assert has_permission("healthcare_partner", Perm.INGEST)
    assert not has_permission("state_health_officer", Perm.READ_LINELIST)
    assert not has_permission("unknown-role", Perm.READ_DASHBOARD)
    assert jurisdiction_filter("cdc_analyst", "TX") is None
    assert jurisdiction_filter("state_health_officer", "TX") == "TX"


@pytest.mark.parametrize("inputs,expected", [
    (RiskInputs(0.05, 0.1, False, 1.0), "green"),
    (RiskInputs(0.45, 0.5, True, 1.25), "yellow"),
    (RiskInputs(0.7, 0.9, True, 1.3), "orange"),
    (RiskInputs(0.95, 0.99, True, 2.0, severity_weight=1.6, hospitalization_risk="very_high"), "red"),
])
def test_risk_levels(inputs, expected):
    ra = assess_risk(inputs)
    assert ra.level == expected
    assert ra.reasons


def test_red_requires_probability():
    ra = assess_risk(RiskInputs(0.3, 1.0, True, 3.0, severity_weight=1.6, hospitalization_risk="very_high", ears_c2=6))
    assert ra.level != "red"


def test_escalation():
    assert escalates(None, "yellow")
    assert escalates("yellow", "orange")
    assert not escalates("orange", "orange")


async def test_dispatch_routes_by_audience():
    msg = AlertMessage("a1", "red", "t", "b", "MEASLES", "48201", "TX",
                       ["epidemiologists", "state_health_department", "cdc_analysts", "healthcare_networks"])
    results = await dispatch(msg)
    channels = {r["channel"]: r["status"] for r in results}
    assert channels["in_app"] == "stored"
    assert channels["log"] == "logged"
    assert channels["webhook"] == "skipped"  # not configured in tests


def test_phi_scrubbing():
    out = scrub_phi("Contact 555-123-4567 or jane@x.org, SSN 123-45-6789, MRN: 00123456")
    assert "555-123-4567" not in out and "jane@x.org" not in out and "123-45-6789" not in out
    assert "00123456" not in out


async def test_hashing_embedder_similarity():
    e = HashingEmbedder(384)
    v = await e.embed(["measles rash fever", "measles fever and rash", "wastewater sampling flow"])
    assert np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-5)
    assert v[0] @ v[1] > v[0] @ v[2]


def test_bm25_and_rrf():
    docs = ["measles case definition rash", "influenza season onset", "dengue vector control"]
    s = bm25_scores("measles rash", docs)
    assert s.argmax() == 0
    fused = rrf([[0, 1], [1, 0]])
    assert fused[0] == pytest.approx(fused[1])


def test_chunking_overlap():
    text = "\n\n".join(" ".join(f"w{i}_{j}" for j in range(100)) for i in range(5))
    chunks = chunk_text(text, max_words=180, overlap=40)
    assert len(chunks) >= 3
    assert all(len(c.split()) <= 180 for c in chunks)
