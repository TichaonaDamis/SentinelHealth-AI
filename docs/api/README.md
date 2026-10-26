# Backend API design

- **Base path:** `/api/v1`
- **Machine-readable spec:** [`openapi.json`](openapi.json), regenerated with `make openapi`
- **Interactive docs:** `/docs` (Swagger UI; disabled when `SENTINEL_ENVIRONMENT=prod`)

## Conventions

| Topic | Convention |
|---|---|
| Auth | OAuth2 password grant → JWT (HS256, 30-min TTL, `iss`, `jti`). Send `Authorization: Bearer <token>`. In production, put an OIDC IdP (Cognito, Okta, Login.gov) in front and map its groups to roles. |
| Authorization | Permission-based RBAC (`app/core/rbac.py`) plus **jurisdiction scoping**: state-level users only see and act on their state, and asking for another state returns `403`. |
| Errors | `{"detail": "..."}` with standard status codes: `401` unauthenticated, `403` forbidden or out of jurisdiction, `404`, `409` conflict, `422` validation, `413` payload too large |
| Idempotency | Signal ingestion is an upsert on `(observed_on, region_id, disease_code)`. Each feed updates only the metrics it supplies. |
| Tracing | Every response carries `x-request-id`, which is also stored in the audit log |
| Pagination | `limit` query parameter (bounded per endpoint). Time filters use `since`, `start` and `end`. |
| Async | All handlers are `async` (SQLAlchemy asyncio + asyncpg). CPU-bound model scoring runs over at most a 90-day panel per request. Long jobs (national scans, retraining) are triggered by Airflow. |

## Endpoints

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/auth/token` | public | Exchange credentials for a JWT (login success and failure are audited) |
| GET | `/auth/me` | any | Current user profile |
| POST / GET | `/auth/users` | `users:manage` | Create (password policy enforced) and list users |
| GET | `/diseases` | any | Monitored conditions |
| GET | `/regions` | any (scoped) | Surveillance regions (FIPS) |
| POST | `/surveillance/signals` | `surveillance:ingest` | Batch-ingest daily signals (≤ 50k records). Creates a lineage batch with a SHA-256 checksum. |
| GET | `/surveillance/signals` | `surveillance:read` | Query time series by disease, region, state and date |
| POST | `/surveillance/cases` | `surveillance:ingest` | De-identified case line list. `patient_ref` is encrypted at rest. |
| GET | `/lineage/batches` | `audit:read` | Ingestion batches (source, checksum, counts, submitter) |
| GET | `/lineage/signal` | `surveillance:read` | Trace one value back to its batch and source object |
| GET | `/analytics/risk` | `analytics:read` | Current risk assessment for every series (no side effects) |
| POST | `/analytics/scan` | `analytics:run` | Detection + classification, persists outbreak events, raises de-duplicated alerts |
| GET | `/analytics/outbreaks` | `analytics:read` | Outbreak events with explanations |
| GET | `/analytics/hotspots` | `linelist:read` | Spatial clusters (`method=hdbscan|dbscan`) with relative risk |
| GET | `/forecasts/{disease}/{region_id}` | `analytics:read` | 7/14/30-day forecast, intervals, hospitalization/mortality risk, outbreak tier |
| GET | `/alerts` | `alerts:read` | Alerts, filterable by status, level, disease and state |
| PATCH | `/alerts/{id}` | `alerts:manage` | Acknowledge, resolve or dismiss, with a note |
| GET | `/dashboard/summary` | `dashboard:read` | KPIs, trend, regional risk map, recent alerts |
| POST | `/copilot/ask` | `copilot:use` | RAG question answering with citations |
| POST | `/copilot/sitrep` | `copilot:use` | Situation report / risk assessment |
| POST / GET | `/copilot/documents` | `copilot:manage` / `copilot:use` | Add or list knowledge-base documents |
| GET | `/admin/audit-logs` | `audit:read` | Audit trail |
| GET | `/admin/models` | `analytics:read` | Loaded model artifact versions |
| GET | `/admin/model-evaluation` | `analytics:read` | Latest evaluation metrics (confusion matrix, ROC, backtests) |
| GET | `/health`, `/ready` | public | Liveness / readiness (DB + models) |

### Role → permission matrix

| Permission | admin | epidemiologist | cdc_analyst | state_health_officer | healthcare_partner | viewer |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| dashboard:read | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| surveillance:read | ✓ | ✓ | ✓ | ✓ | | |
| surveillance:ingest | ✓ | | | | ✓ | |
| linelist:read | ✓ | ✓ | ✓ | | | |
| analytics:read / run | ✓ | ✓ | ✓ | ✓ | | |
| alerts:read | ✓ | ✓ | ✓ | ✓ | ✓ | |
| alerts:manage | ✓ | ✓ | ✓ | ✓ | | |
| copilot:use | ✓ | ✓ | ✓ | ✓ | | |
| copilot:manage | ✓ | ✓ | | | | |
| audit:read, users:manage | ✓ | | | | | |
| **Scope** | national | national or state | national | own state | own state | national or state |

## Examples

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/token \
  -d 'username=epi@sentinelhealth.dev&password=ChangeMe!2026' | jq -r .access_token)

# Ingest syndromic ED visits (partial update of the daily signal)
curl -s -X POST localhost:8000/api/v1/surveillance/signals -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{
    "source": "syndromic", "pipeline_run_id": "essence-2026-10-26",
    "records": [{"observed_on": "2026-10-25", "region_id": "48201", "disease_code": "INFLUENZA", "ed_visits": 412}]
  }'

# Run detection + alerting
curl -s -X POST localhost:8000/api/v1/analytics/scan -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"notify": true}' | jq '.signals, .alerts_created'

# Forecast
curl -s localhost:8000/api/v1/forecasts/INFLUENZA/48201 -H "Authorization: Bearer $TOKEN" | jq '.horizons'
```

Example `RiskAssessmentOut` from `GET /analytics/risk`:

```json
{
  "disease_code": "CLI", "region_id": "13121", "region_name": "Atlanta", "state": "GA", "as_of": "2026-10-25",
  "risk_level": "orange", "risk_score": 70.0, "outbreak_probability": 1.0, "outbreak_tier": "High",
  "anomaly_score": 0.98, "anomaly_flag": true, "ears_c2": 4.1, "incidence_7d_per_100k": 111.4, "growth_7d": 1.87,
  "drivers": [{"feature": "otc_ratio_7_28", "value": 2.31}, {"feature": "incidence_7d_per_100k", "value": 1.92}],
  "reasons": ["High outbreak likelihood (100%)", "Multi-source anomaly detected (syndromic/lab/wastewater)",
              "Rapid growth: cases ×1.9 week-over-week"]
}
```
