# Testing strategy

## Test pyramid

| Layer | Location | What it proves | Runs in |
|---|---|---|---|
| ML unit tests | `tests/ml/` | Synthetic data properties; **no look-ahead in features**; EARS C2; detectors rank outbreaks higher; classifier AUC > 0.8 with metric integrity; forecasters produce ordered intervals; HDBSCAN/DBSCAN recover an injected cluster; event-level lead-time maths; registry checksum tamper detection | CI `python` job |
| Backend unit tests | `tests/backend/test_services.py` | Password hashing, JWT round-trip, RBAC matrix, risk-level rules and guard rails, escalation logic, notification routing, PHI scrubbing, embeddings, BM25 + RRF, chunking | CI `python` job |
| API integration tests | `tests/backend/test_api.py` | End-to-end on a seeded database: authentication, RBAC denials, **jurisdiction scoping**, risk assessment, scan → events → **de-duplicated alerts**, acknowledgement, forecasts, hotspots, dashboard, **lineage**, **encryption at rest**, copilot citations, sitrep, **audit trail** (logins, failures, denials), password policy | CI `python` job |
| Pipeline tests | `tests/pipeline/` | MMWR week maths, validation and quarantine rules, NNDSS mapping, bronze lake round trip | CI `python` job |
| Model smoke test | `train_all --quick` | The full training and evaluation pipeline runs and writes a report | CI `python` job |
| Migration tests | CI `migrations` job | `alembic upgrade → downgrade → upgrade` on TimescaleDB + PostGIS + pgvector; seed + scan + warehouse ETL on PostgreSQL | CI |
| Frontend static checks | `npm run lint`, `npm run typecheck`, `next build` | Type safety and a production build | CI `frontend` job |
| Infrastructure | `terraform fmt -check`, `terraform validate` (dev + prod), Checkov | IaC correctness and security misconfiguration | CI `terraform`, `security` jobs |
| Security | gitleaks, pip-audit, npm audit, Trivy | Secrets, vulnerable dependencies, image CVEs | CI `security`, `images` jobs |

Run everything locally with `make test lint typecheck`. Current status: **48 Python tests pass** (backend, ML, pipeline).

## What's verified manually or in staging

| Area | Approach |
|---|---|
| UI flows | Playwright: log in, view dashboard, triage an alert, run the copilot. Screenshots are in `docs/images/ui/`. The suggested next step is to add `frontend/e2e/*.spec.ts` against the compose stack. |
| Load | k6 or Locust against `/dashboard/summary`, `/analytics/risk` and ingestion (50k-record batches). Targets: p95 < 2 s at 200 RPS; ingest 1M signals in < 10 min. |
| LLM copilot | Groundedness eval set (numbers must match `[F#]`), retrieval recall@k, red-team prompts for PHI and unsafe advice |
| Model validation on real data | Retrospective study per jurisdiction before go-live (see [ml-pipeline.md](ml-pipeline.md#5-validation-methodology)) |
| DR | Quarterly restore drill: RDS PITR to a new instance, redeploy the stack in a second region from Terraform |
| Security | Annual third-party pen test; quarterly access reviews from the audit log |

## Test data policy

- **Never use real PHI in tests, fixtures, screenshots or logs.** All test data comes from `sentinel_ml.data.synthetic`.
- Demo credentials exist only in seed data and test fixtures.
