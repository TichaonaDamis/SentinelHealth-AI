# SentinelHealth Airflow pipelines

| DAG | Schedule | Purpose |
|---|---|---|
| `ingest_public_sources` | daily 06:00 UTC | CDC NNDSS, CDC NWSS wastewater, HealthData.gov hospital admissions, WHO FluNet → bronze/silver lake → API (lineage batches) |
| `ingest_partner_feeds` | hourly | Syndromic (ESSENCE exports), hospital, pharmacy and environmental-sensor files from the S3 landing zone |
| `surveillance_pipeline` | daily 08:00 UTC | Anomaly scan + alerting → 7/14/30-day forecasts → Kimball warehouse load (`dags/sql/load_warehouse.sql`) |
| `model_retraining` | weekly (Sun 03:00) | Champion/challenger retraining, gated promotion to the S3 model registry, ECS rolling restart |

## Configuration

Environment variables (Secrets Manager backend in AWS):

| Variable | Meaning |
|---|---|
| `SENTINEL_API_URL`, `SENTINEL_API_USER`, `SENTINEL_API_PASSWORD` | Service account used to load data and trigger scans (role `healthcare_partner` + `epidemiologist` permissions, or `admin`) |
| `SENTINEL_LAKE_BUCKET`, `SENTINEL_LAKE_KMS_KEY_ID` | Data lake bucket (bronze/silver/quarantine). If unset, writes to `SENTINEL_LAKE_DIR` locally |
| `SENTINEL_LANDING_BUCKET` | Partner drop-zone bucket |
| `SENTINEL_MODEL_BUCKET`, `SENTINEL_ECS_CLUSTER`, `SENTINEL_API_SERVICE` | Model registry and the service restarted after promotion |
| `SOCRATA_APP_TOKEN` | Optional; raises Socrata rate limits for data.cdc.gov / healthdata.gov |

Airflow connection `sentinel_warehouse` (Postgres) is used by the warehouse load and the training export.

Dataset identifiers for public portals are Airflow Variables (`cdc_nndss_dataset`, `cdc_nwss_dataset`,
`healthdata_hospital_dataset`) because portals occasionally re-issue datasets. Check the current IDs and
column names before you enable a source in a new environment. Normalisers in
`plugins/sentinel_connectors/normalize.py` map source columns to the canonical schema, and rows that fail
validation go to the `quarantine/` zone with a reason.
