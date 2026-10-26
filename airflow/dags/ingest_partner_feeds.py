"""Hourly ingestion of partner feeds dropped in the S3 landing zone.

Partners (hospital networks, syndromic surveillance/ESSENCE exports, pharmacy
chains, environmental sensor networks) deliver CSV/JSON files to
``s3://<landing>/<feed>/``. Files are processed exactly once (moved to
``processed/`` or ``failed/``) and every file becomes one lineage batch.

Expected columns per feed (after mapping):
* syndromic   date, fips, syndrome, visits           -> ed_visits
* hospital    date, fips, condition, admissions      -> admissions
* pharmacy    date, fips, category, units_index      -> otc_sales
* environment date, fips, target, concentration_idx  -> wastewater
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta

import pandas as pd
from airflow.decorators import dag, task

from sentinel_connectors import lake, normalize
from sentinel_connectors.api_client import SentinelAPI

FEEDS = {
    "syndromic": {"metric": "ed_visits", "value": "visits", "code_col": "syndrome",
                  "codes": {"ILI": "INFLUENZA", "CLI": "CLI", "RSV": "RSV", "GI": "FOODBORNE",
                            "FEVER_RASH": "MEASLES", "DENGUE_LIKE": "DENGUE"}},
    "hospital": {"metric": "admissions", "value": "admissions", "code_col": "condition",
                 "codes": {"influenza": "INFLUENZA", "covid": "CLI", "rsv": "RSV", "measles": "MEASLES",
                           "dengue": "DENGUE", "enteric": "FOODBORNE"}},
    "pharmacy": {"metric": "otc_sales", "value": "units_index", "code_col": "category",
                 "codes": {"cough_cold": "INFLUENZA", "antidiarrheal": "FOODBORNE", "fever_reducer": "CLI"}},
    "environment": {"metric": "wastewater", "value": "concentration_idx", "code_col": "target",
                    "codes": {"influenza_a": "INFLUENZA", "sars_cov_2": "CLI", "rsv": "RSV", "measles": "MEASLES"}},
}


@dag(
    dag_id="ingest_partner_feeds",
    schedule="15 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "sentinel-data-eng", "retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["ingestion", "partners"],
    doc_md=__doc__,
)
def ingest_partner_feeds():
    @task
    def list_files(feed: str) -> list[str]:
        import boto3

        bucket = os.environ["SENTINEL_LANDING_BUCKET"]
        resp = boto3.client("s3").list_objects_v2(Bucket=bucket, Prefix=f"{feed}/incoming/")
        return [o["Key"] for o in resp.get("Contents", []) if o["Key"].endswith((".csv", ".json"))][:200]

    @task
    def process(feed: str, keys: list[str], ds=None, run_id=None) -> list[dict]:
        import boto3

        s3 = boto3.client("s3")
        bucket = os.environ["SENTINEL_LANDING_BUCKET"]
        cfg = FEEDS[feed]
        api = SentinelAPI()
        out = []
        for key in keys:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            raw = pd.read_csv(io.BytesIO(body)) if key.endswith(".csv") else pd.read_json(io.BytesIO(body))
            bronze = lake.write_bronze(feed, raw.to_dict(orient="records"), pd.Timestamp(ds).date(),
                                       f"{run_id}-{os.path.basename(key)}")
            df = pd.DataFrame({
                "observed_on": raw["date"],
                "region_id": raw["fips"].astype(str).str.zfill(5),
                "disease_code": raw[cfg["code_col"]].map(cfg["codes"]),
                cfg["metric"]: raw[cfg["value"]],
            })
            res = normalize.validate(df)
            dest = "failed" if res.valid.empty else "processed"
            if not res.valid.empty:
                api.ingest_signals(res.valid, source=f"partner_{feed}", source_uri=bronze.uri, run_id=run_id)
            if len(res.rejected):
                lake.write_silver(f"quarantine/{feed}", res.rejected, pd.Timestamp(ds).date(), run_id)
            s3.copy_object(Bucket=bucket, Key=key.replace("/incoming/", f"/{dest}/"),
                           CopySource={"Bucket": bucket, "Key": key})
            s3.delete_object(Bucket=bucket, Key=key)
            out.append({"key": key, **res.stats})
        return out

    for feed in FEEDS:
        process.override(task_id=f"process_{feed}")(feed, list_files.override(task_id=f"list_{feed}")(feed))


ingest_partner_feeds()
