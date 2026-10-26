"""Daily surveillance analytics: detection -> alerts -> forecasts -> warehouse load.

Runs after ``ingest_public_sources`` completes for the same logical date.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from airflow.decorators import dag, task
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.sensors.external_task import ExternalTaskSensor

from sentinel_connectors.api_client import SentinelAPI

SQL_DIR = Path(__file__).parent / "sql"


@dag(
    dag_id="surveillance_pipeline",
    schedule="0 8 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "sentinel-analytics", "retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["analytics", "alerts", "forecasting"],
    template_searchpath=[str(SQL_DIR)],
    doc_md=__doc__,
)
def surveillance_pipeline():
    wait_ingest = ExternalTaskSensor(
        task_id="wait_for_ingestion", external_dag_id="ingest_public_sources", external_task_id=None,
        execution_delta=timedelta(hours=2), mode="reschedule", timeout=4 * 3600, poke_interval=300,
        allowed_states=["success"], failed_states=["failed"],
    )

    @task
    def detect_and_alert(ds=None) -> dict:
        result = SentinelAPI().scan(as_of=None)
        return {"as_of": result["as_of"], "evaluated": result["evaluated"], "signals": result["signals"],
                "alerts_created": result["alerts_created"]}

    @task
    def forecast_all() -> dict:
        api = SentinelAPI()
        ok = failed = 0
        for region in api.regions():
            for disease in api.diseases():
                try:
                    api.forecast(disease["code"], region["id"])
                    ok += 1
                except Exception:
                    failed += 1
        if failed > ok:
            raise RuntimeError(f"forecasting failed for {failed} series")
        return {"forecasts": ok, "failed": failed}

    load_warehouse = SQLExecuteQueryOperator(
        task_id="load_warehouse", conn_id="sentinel_warehouse", sql="load_warehouse.sql", split_statements=True,
    )

    wait_ingest >> detect_and_alert() >> forecast_all() >> load_warehouse


surveillance_pipeline()
