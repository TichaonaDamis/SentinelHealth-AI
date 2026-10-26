import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "airflow" / "plugins"))

from sentinel_connectors import lake, normalize  # noqa: E402


def test_mmwr_week_end():
    # MMWR 2025 week 1 runs Sun 2024-12-29 .. Sat 2025-01-04
    assert normalize._mmwr_week_end(2025, 1) == date(2025, 1, 4)
    assert normalize._mmwr_week_end(2021, 1) == date(2021, 1, 9)


def test_validate_quarantines_bad_rows():
    df = pd.DataFrame([
        {"observed_on": "2026-01-05", "region_id": "48201", "disease_code": "INFLUENZA", "cases": 10},
        {"observed_on": "not-a-date", "region_id": "48201", "disease_code": "INFLUENZA", "cases": 3},
        {"observed_on": "2026-01-05", "region_id": "99999", "disease_code": "INFLUENZA", "cases": 3},
        {"observed_on": "2026-01-06", "region_id": "48201", "disease_code": "INFLUENZA", "cases": -1},
        {"observed_on": "2026-01-07", "region_id": "48201", "disease_code": "INFLUENZA", "positivity": 12.5},
        {"observed_on": "2026-01-08", "region_id": "48201", "disease_code": "INFLUENZA"},
    ])
    res = normalize.validate(df, known_regions={"48201"}, known_diseases={"INFLUENZA"})
    assert res.stats == {"input": 6, "valid": 2, "rejected": 4}
    assert res.valid["positivity"].dropna().iloc[0] == 0.125  # percentage converted to proportion
    reasons = " ".join(res.rejected["reject_reason"])
    for r in ("bad_date", "unknown_region", "negative_cases", "no_metrics"):
        assert r in reasons


def test_nndss_mapping():
    recs = [{"states": "TEXAS", "year": "2026", "week": "3", "label": "Measles, Indigenous", "m1": "4"},
            {"states": "TEXAS", "year": "2026", "week": "3", "label": "Some other condition", "m1": "9"}]
    out = normalize.normalize_nndss(recs, {"TX": "48201"})
    assert len(out) == 1
    row = out.iloc[0]
    assert row.disease_code == "MEASLES" and row.region_id == "48201" and row.cases == 4


def test_bronze_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_LAKE_DIR", str(tmp_path))
    monkeypatch.delenv("SENTINEL_LAKE_BUCKET", raising=False)
    obj = lake.write_bronze("cdc_nwss", [{"a": 1}, {"a": 2}], date(2026, 1, 1), "manual__2026-01-01T00:00")
    assert obj.records == 2 and len(obj.sha256) == 64
    assert "bronze/cdc_nwss/ingest_date=2026-01-01/" in obj.uri
    assert lake.read_bronze(obj.uri) == [{"a": 1}, {"a": 2}]
