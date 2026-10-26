"""Least-privilege database roles and row-level security for jurisdiction isolation.

* ``sentinel_api``      runtime role for the API (no DDL, INSERT-only on audit_logs)
* ``sentinel_etl``      Airflow role (writes signals/facts, no access to users or audit)
* ``sentinel_readonly`` BI / analyst role on the warehouse schema only

Passwords are not set here; in AWS these roles authenticate with IAM database
authentication (``rds_iam``) so no static credentials exist.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

from alembic import op

from app.db.migration_utils import execute_script

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = r"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentinel_api') THEN CREATE ROLE sentinel_api LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentinel_etl') THEN CREATE ROLE sentinel_etl LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentinel_readonly') THEN CREATE ROLE sentinel_readonly LOGIN; END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam') THEN
    GRANT rds_iam TO sentinel_api, sentinel_etl, sentinel_readonly;
  END IF;
END $$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO sentinel_api, sentinel_etl;
GRANT SELECT, INSERT, UPDATE ON users, diseases, regions, daily_signals, case_reports, lab_reports,
      hospital_admissions, outbreak_events, alerts, forecasts, ingestion_batches,
      knowledge_documents, knowledge_chunks TO sentinel_api;
GRANT DELETE ON knowledge_documents, knowledge_chunks TO sentinel_api;
GRANT SELECT, INSERT ON audit_logs TO sentinel_api;
GRANT SELECT ON daily_signals_weekly TO sentinel_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO sentinel_api, sentinel_etl;

GRANT SELECT ON diseases, regions TO sentinel_etl;
GRANT SELECT, INSERT, UPDATE ON daily_signals, case_reports, lab_reports, hospital_admissions,
      ingestion_batches, knowledge_documents, knowledge_chunks TO sentinel_etl;
GRANT SELECT ON alerts, outbreak_events, forecasts TO sentinel_etl;

GRANT USAGE ON SCHEMA warehouse TO sentinel_etl, sentinel_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA warehouse TO sentinel_etl;
GRANT SELECT ON ALL TABLES IN SCHEMA warehouse TO sentinel_readonly;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA warehouse TO sentinel_etl;

-- Row-level security on the line list: when the API sets app.jurisdiction for a state-scoped user,
-- only that state's cases are visible even if an application-level filter were missed.
ALTER TABLE case_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY case_reports_jurisdiction ON case_reports
  USING (
    coalesce(current_setting('app.jurisdiction', true), '') = ''
    OR region_id IN (SELECT id FROM regions WHERE state = current_setting('app.jurisdiction', true))
  );
"""

DOWNGRADE = r"""
DROP POLICY IF EXISTS case_reports_jurisdiction ON case_reports;
ALTER TABLE case_reports DISABLE ROW LEVEL SECURITY;
"""


def upgrade() -> None:
    execute_script(op, UPGRADE)


def downgrade() -> None:
    execute_script(op, DOWNGRADE)
