"""Daily ingestion of public surveillance sources.

CDC NNDSS (notifiable diseases), CDC NWSS (wastewater), HealthData.gov
(hospital admissions) and WHO FluNet (global influenza context).

Each source: fetch -> bronze (raw, immutable) -> normalise + validate -> silver
(parquet) + quarantine -> load to the API (which records lineage per batch).
Sources are independent task groups so one portal outage does not block others.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from airflow.decorators import dag, task
from airflow.models import Variable

from sentinel_connectors import lake, normalize, sources
from sentinel_connectors.api_client import SentinelAPI

DEFAULT_ARGS = {
    "owner": "sentinel-data-eng",
    "retries": 3,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(hours=1),
}

SOURCES = {
    "cdc_nndss": (sources.fetch_cdc_nndss, "cdc_nndss_dataset", "x9gk-5huc", 42),
    "cdc_nwss": (sources.fetch_cdc_nwss_wastewater, "cdc_nwss_dataset", "2ew6-ywp6", 21),
    "healthdata_hospital": (sources.fetch_healthdata_hospital, "healthdata_hospital_dataset", "g62h-syeh", 21),
}


@dag(
    dag_id="ingest_public_sources",
    schedule="0 6 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["ingestion", "public-data"],
    doc_md=__doc__,
)
def ingest_public_sources():
    @task
    def reference() -> dict:
        api = SentinelAPI()
        regions = api.regions()
        # Most populous monitored region per state receives state-level aggregates.
        by_state: dict[str, dict] = {}
        for r in regions:
            if r["state"] not in by_state or r["population"] > by_state[r["state"]]["population"]:
                by_state[r["state"]] = r
        return {
            "state_to_region": {s: r["id"] for s, r in by_state.items()},
            "regions": [r["id"] for r in regions],
            "diseases": [d["code"] for d in api.diseases()],
        }

    @task
    def extract(source: str, ds=None, run_id=None) -> dict:
        fetch, var_name, default_dataset, lookback_days = SOURCES[source]
        since = (pd.Timestamp(ds) - pd.Timedelta(days=lookback_days)).date()
        records, uri = fetch(since, dataset_id=Variable.get(var_name, default_var=default_dataset))
        obj = lake.write_bronze(source, records, pd.Timestamp(ds).date(), run_id)
        # Only the lake URI travels through XCom; payloads can be millions of rows.
        return {"source": source, "bronze_uri": obj.uri, "sha256": obj.sha256, "records": obj.records,
                "source_uri": uri}

    @task
    def transform_and_load(extracted: dict, ref: dict, ds=None, run_id=None) -> dict:
        src = extracted["source"]
        raw = lake.read_bronze(extracted["bronze_uri"])
        if src == "cdc_nndss":
            df = normalize.normalize_nndss(raw, ref["state_to_region"])
        elif src == "cdc_nwss":
            df = normalize.normalize_nwss(raw)
        else:
            df = normalize.normalize_healthdata_hospital(raw, ref["state_to_region"])
        res = normalize.validate(df, set(ref["regions"]), set(ref["diseases"]))
        day = pd.Timestamp(ds).date()
        silver = lake.write_silver(src, res.valid, day, run_id)
        if len(res.rejected):
            lake.write_silver(f"quarantine/{src}", res.rejected, day, run_id)
        loaded = SentinelAPI().ingest_signals(res.valid, source=src, source_uri=extracted["bronze_uri"], run_id=run_id) \
            if len(res.valid) else []
        return {**extracted, "silver_uri": silver.uri, **res.stats,
                "batches": [b["batch_id"] for b in loaded]}

    @task
    def who_flunet(ds=None, run_id=None) -> dict:
        """Global influenza context stored in the lake (not mapped to US regions)."""
        since = (pd.Timestamp(ds) - pd.Timedelta(days=90)).date()
        records, uri = sources.fetch_who_flunet(since)
        obj = lake.write_bronze("who_flunet", records, pd.Timestamp(ds).date(), run_id)
        return {"bronze_uri": obj.uri, "records": obj.records, "source_uri": uri}

    ref = reference()
    for name in SOURCES:
        transform_and_load.override(task_id=f"load_{name}")(extract.override(task_id=f"extract_{name}")(name), ref)
    who_flunet()


ingest_public_sources()
