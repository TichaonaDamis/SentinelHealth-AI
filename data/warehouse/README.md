# Kimball warehouse

- **DDL:** [`backend/alembic/versions/0002_kimball_warehouse.py`](../../backend/alembic/versions/0002_kimball_warehouse.py)
- **Incremental load:** [`airflow/dags/sql/load_warehouse.sql`](../../airflow/dags/sql/load_warehouse.sql). It runs daily in the `surveillance_pipeline` DAG; to run it by hand: `psql -f airflow/dags/sql/load_warehouse.sql`.
- **Star schema diagram and example queries:** [`docs/database-schema.md`](../../docs/database-schema.md#2-kimball-star-schema)

Dimensions: `dim_date` (MMWR epi-weeks, respiratory season), `dim_location` (SCD2), `dim_disease`, `dim_facility` (SCD2), `dim_population`.
Facts: `fact_cases`, `fact_hospitalizations`, `fact_vaccinations`, `fact_lab_results`, `fact_alerts`.
