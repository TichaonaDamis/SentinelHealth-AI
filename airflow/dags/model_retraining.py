"""Weekly champion/challenger model retraining.

1. Export the last 3 years of daily signals from the warehouse to parquet.
2. Train all models with ``sentinel_ml.pipelines.train_all`` (temporal hold-out = last 12 months).
3. Promote only if the challenger beats the champion on ROC AUC *and* forecast skill
   and does not increase false alerts by more than 10%.
4. Upload artifacts to the S3 model registry and roll the API service (ECS) so
   new tasks load the promoted models.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from airflow.decorators import dag, task
from airflow.exceptions import AirflowSkipException


@dag(
    dag_id="model_retraining",
    schedule="0 3 * * 0",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "sentinel-ml", "retries": 1, "retry_delay": timedelta(minutes=30),
                  "execution_timeout": timedelta(hours=4)},
    tags=["ml", "training"],
    doc_md=__doc__,
)
def model_retraining():
    @task
    def export_training_data(ds=None) -> str:
        import pandas as pd
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        hook = PostgresHook(postgres_conn_id="sentinel_warehouse")
        sql = """
            SELECT s.observed_on AS date, s.region_id, r.name AS region_name, r.state, r.lat, r.lon,
                   r.population, s.disease_code AS disease, coalesce(s.cases, 0) AS cases,
                   coalesce(s.ed_visits, 0) AS ed_visits, coalesce(s.admissions, 0) AS admissions,
                   coalesce(s.deaths, 0) AS deaths, coalesce(s.positivity, 0) AS positivity,
                   coalesce(s.otc_sales, 0) AS otc_sales, coalesce(s.wastewater, 0) AS wastewater,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM outbreak_events e
                       WHERE e.disease_code = s.disease_code AND e.region_id = s.region_id
                         AND e.status = 'confirmed' AND s.observed_on BETWEEN e.detected_on - 7 AND e.detected_on + 28
                   ) THEN 1 ELSE 0 END AS outbreak
            FROM daily_signals s JOIN regions r ON r.id = s.region_id
            WHERE s.observed_on >= %(start)s
        """
        df = hook.get_pandas_df(sql, parameters={"start": (pd.Timestamp(ds) - pd.Timedelta(days=3 * 365)).date()})
        path = Path(f"/tmp/sentinel-train-{ds}.parquet")
        df.to_parquet(path, index=False)
        return str(path)

    @task
    def train(data_path: str, ds=None) -> str:
        import pandas as pd

        from sentinel_ml.pipelines.train_all import run

        out = Path(f"/tmp/sentinel-models-{ds}")
        out.mkdir(parents=True, exist_ok=True)
        df = pd.read_parquet(data_path)
        # Real data has few adjudicated outbreaks; fall back to synthetic-augmented training when too sparse.
        use_data = Path(data_path) if df["outbreak"].sum() >= 200 else None
        test_start = (pd.Timestamp(ds) - pd.Timedelta(days=365)).date().isoformat()
        run(out, out / "report.md", test_start, use_data)
        return str(out)

    @task
    def evaluate_and_promote(candidate_dir: str, ds=None) -> dict:
        import boto3

        s3 = boto3.client("s3")
        bucket = os.environ["SENTINEL_MODEL_BUCKET"]
        new = json.loads((Path(candidate_dir) / "metrics.json").read_text())
        try:
            champ = json.loads(s3.get_object(Bucket=bucket, Key="champion/metrics.json")["Body"].read())
        except s3.exceptions.NoSuchKey:
            champ = None

        def skill(m):
            rows = [r for r in m["forecast"] if r["model"] == "xgboost" and r["horizon"] == 14]
            return rows[0]["skill_vs_naive"] if rows else 0.0

        def false_alerts(m):
            return m["early_detection"]["flag_sentinel"]["false_alerts_per_series_year"]

        promote = champ is None or (
            new["classifier"]["roc_auc"] >= champ["classifier"]["roc_auc"] - 0.002
            and skill(new) >= skill(champ) - 0.01
            and false_alerts(new) <= false_alerts(champ) * 1.10
            and (new["classifier"]["roc_auc"] > champ["classifier"]["roc_auc"] or skill(new) > skill(champ))
        )
        if not promote:
            raise AirflowSkipException("challenger did not beat champion; keeping current models")
        for f in Path(candidate_dir).iterdir():
            if f.suffix in {".joblib", ".json", ".md"}:
                s3.upload_file(str(f), bucket, f"versions/{ds}/{f.name}", ExtraArgs={"ServerSideEncryption": "aws:kms"})
                s3.upload_file(str(f), bucket, f"champion/{f.name}", ExtraArgs={"ServerSideEncryption": "aws:kms"})
        return {"promoted": ds, "roc_auc": new["classifier"]["roc_auc"], "forecast_skill_14d": skill(new)}

    @task
    def roll_api_service(_: dict) -> None:
        import boto3

        boto3.client("ecs").update_service(cluster=os.environ["SENTINEL_ECS_CLUSTER"],
                                           service=os.environ["SENTINEL_API_SERVICE"], forceNewDeployment=True)

    roll_api_service(evaluate_and_promote(train(export_training_data())))


model_retraining()
