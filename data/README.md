# Data

| Path | Contents |
|---|---|
| `synthetic/sample_surveillance_panel.csv` | A small sample of the synthetic multi-source panel: 5 regions × 3 diseases × 120 days. The full dataset is generated on demand by `sentinel_ml.data.synthetic` and is never committed. |
| `warehouse/` | Notes and example queries for the Kimball warehouse (DDL is in the Alembic migrations) |

No real patient data belongs in this repository. Locally, the data lake writes to `SENTINEL_LAKE_DIR` (default `/tmp/sentinel-lake`); in AWS it writes to the S3 raw and lake buckets.

## Panel schema (canonical daily signal)

| Column | Description |
|---|---|
| `date` | Observation date (onset date for cases) |
| `region_id` | County FIPS code |
| `disease` | `INFLUENZA`, `CLI`, `RSV`, `MEASLES`, `DENGUE`, `FOODBORNE` |
| `cases` | Confirmed cases by onset date |
| `ed_visits` | Syndromic emergency-department visits (leads cases by ~2 days) |
| `admissions` | Hospital admissions (lags by ~3 days) |
| `deaths` | Deaths (lags by ~10 days) |
| `positivity` | Laboratory test positivity (0-1) |
| `otc_sales` | Pharmacy over-the-counter sales index (leads by ~5 days) |
| `wastewater` | Wastewater viral concentration index (leads by ~5 days) |
| `outbreak` | Ground-truth label (synthetic data only) |
