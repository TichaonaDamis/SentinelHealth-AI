# System architecture

SentinelHealth AI ingests fragmented surveillance feeds, normalizes them into one time-series model, and runs detection, forecasting and risk scoring on top. It alerts the right people and gives epidemiologists an explainable copilot over all of it.

## 1. Logical architecture

```mermaid
flowchart LR
  subgraph Sources["Data sources"]
    CDC["CDC Open Data<br/>NNDSS · NWSS wastewater"]
    WHO["WHO FluNet / GHO"]
    HDG["HealthData.gov<br/>hospital capacity"]
    SYN["Syndromic feeds<br/>(ESSENCE exports)"]
    HOSP["Hospital EHR feeds<br/>(FHIR Bulk $export)"]
    PHARM["Pharmacy OTC sales"]
    ENV["Environmental sensors"]
  end

  subgraph Ingest["Ingestion (Airflow / MWAA)"]
    LAND["S3 landing zone<br/>+ validator Lambda"]
    BRONZE[("S3 bronze<br/>raw, Object Lock")]
    NORM["Normalize & validate<br/>quarantine bad rows"]
    SILVER[("S3 silver<br/>parquet")]
  end

  subgraph Core["Platform core (ECS Fargate)"]
    API["FastAPI<br/>REST · RBAC · audit"]
    ML["sentinel_ml<br/>anomaly · forecast · classify · cluster"]
    RISK["Risk engine<br/>Green/Yellow/Orange/Red"]
    NOTIFY["Notification router"]
    COPILOT["RAG copilot<br/>Claude → OpenAI → offline"]
  end

  subgraph Data["Data stores"]
    PG[("PostgreSQL 16<br/>PostGIS · pgvector · TimescaleDB*")]
    DW[("Kimball warehouse<br/>schema: warehouse")]
    OS[("OpenSearch<br/>hybrid BM25 + k-NN")]
    REG[("S3 model registry")]
  end

  subgraph Users["Consumers"]
    WEB["Next.js dashboard"]
    EPI["Epidemiologists"]
    STATE["State health depts"]
    CDCU["CDC analysts"]
    NET["Healthcare networks"]
  end

  CDC & WHO & HDG --> BRONZE
  SYN & HOSP & PHARM & ENV --> LAND --> BRONZE
  BRONZE --> NORM --> SILVER
  NORM -->|"signals + lineage batch"| API
  API <--> PG
  API --> ML --> RISK --> NOTIFY
  REG --> ML
  PG --> DW
  COPILOT <--> OS
  COPILOT <--> PG
  API --> COPILOT
  WEB -->|"BFF, httpOnly session"| API
  NOTIFY -->|"in-app · email (SES)"| EPI
  NOTIFY -->|"SMS (SNS)"| STATE
  NOTIFY -->|"email"| CDCU
  NOTIFY -->|"signed webhook (Lambda)"| NET
```

\* TimescaleDB runs when the server provides it (self-managed or Timescale Cloud). On Amazon RDS, which does not ship TimescaleDB, the migrations fall back to BRIN-indexed tables and plain materialized views. See [database-schema.md](database-schema.md#timescaledb-vs-amazon-rds).

## 2. AWS deployment architecture

```mermaid
flowchart TB
  user(("Users")) --> WAF["AWS WAF<br/>managed rules + rate limit"] --> ALB["Application Load Balancer<br/>TLS 1.3"]
  partner(("Partners")) --> APIGW["API Gateway HTTP API<br/>mTLS · throttling"] --> VPCL["VPC Link"]

  subgraph VPC["VPC (3 AZs)"]
    subgraph Public["Public subnets"]
      ALB
      NAT["NAT gateways"]
    end
    subgraph Private["Private subnets"]
      WEBS["ECS service: web<br/>(Next.js)"]
      APIS["ECS service: api<br/>(FastAPI, autoscaling 2-40)"]
      MIG["ECS task: migrate"]
      MWAA["MWAA (Airflow)"]
      LMB["Lambda: alert fan-out,<br/>landing validator"]
      VPCL
      CM["Cloud Map: api.sentinel.internal"]
    end
    subgraph Isolated["Isolated subnets (no internet route)"]
      RDS[("RDS PostgreSQL 16<br/>Multi-AZ, KMS, IAM auth")]
      OSD[("OpenSearch domain<br/>VPC-only, FGAC")]
    end
    VPCE["VPC endpoints: S3, ECR, Secrets Manager,<br/>KMS, Logs, STS, SSM"]
  end

  ALB -->|"/"| WEBS
  ALB -->|"/api/*"| APIS
  VPCL --> CM --> APIS
  WEBS --> ALB
  APIS --> RDS
  APIS --> OSD
  MWAA --> APIS
  MWAA --> RDS
  APIS --> SNS["SNS alerts topic"] --> LMB
  S3[("S3: raw · lake · landing · models · audit · mwaa")] --- VPCE
  CW["CloudWatch logs, metrics, alarms"] --- APIS
  CT["CloudTrail · GuardDuty · Security Hub · AWS Config (HIPAA pack)"]
  KMS["KMS CMKs: data · logs · secrets"]
```

Terraform for all of the above lives in [`infrastructure/terraform`](../infrastructure/terraform). It has one module per concern, a `stack` that composes them, and `environments/dev` and `environments/prod`.

## 3. Request and data flows

### 3.1 Daily surveillance cycle

```mermaid
sequenceDiagram
  autonumber
  participant AF as Airflow
  participant SRC as Public / partner sources
  participant S3 as Data lake
  participant API as SentinelHealth API
  participant DB as PostgreSQL
  participant ML as sentinel_ml
  participant N as Notifications

  AF->>SRC: fetch (Socrata, OData, FHIR $export, S3 drops)
  AF->>S3: write bronze (raw, checksum)
  AF->>AF: normalize + validate (quarantine failures)
  AF->>API: POST /surveillance/signals (batch, run id)
  API->>DB: upsert daily_signals + ingestion_batches (lineage)
  AF->>API: POST /analytics/scan
  API->>DB: load 90-day panel
  API->>ML: features → anomaly ensemble + outbreak classifier
  ML-->>API: scores, probabilities, TreeSHAP drivers
  API->>API: risk engine → level + reasons
  API->>DB: outbreak_events, alerts (7-day de-duplication)
  API->>N: route by level & jurisdiction
  AF->>API: GET /forecasts/{disease}/{region} for every series
  AF->>DB: load Kimball warehouse (load_warehouse.sql)
```

### 3.2 Interactive request

The browser never holds the API token. Next.js BFF routes (`/bff/*`) exchange credentials for a JWT, which is stored in an `httpOnly; Secure; SameSite=Strict` cookie. Each request is then proxied to the API with the bearer token attached. The API checks the JWT, then RBAC permission and jurisdiction scope, and then writes an audit record for the request.

## 4. Components

| Component | Tech | Responsibility |
|---|---|---|
| `frontend/` | Next.js 15, TypeScript, Tailwind, shadcn/ui, Recharts, Mapbox GL (with offline SVG fallback), Framer Motion | Executive dashboard, alerts triage, forecasts, copilot, model performance, audit log |
| `backend/` | FastAPI, SQLAlchemy 2 (async), Pydantic v2, Alembic | REST API, auth/RBAC, audit, lineage, scan orchestration, notification routing, RAG copilot |
| `ml/` (`sentinel_ml`) | pandas, NumPy, scikit-learn, XGBoost, LightGBM, PyTorch (optional), Prophet (optional) | Synthetic data, features, anomaly detectors, forecasters, outbreak classifier, spatial clustering, evaluation, registry |
| `airflow/` | Apache Airflow 2.10 (MWAA) | Ingestion DAGs, daily surveillance pipeline, warehouse ETL, weekly retraining |
| `infrastructure/` | Terraform, AWS Lambda | VPC, KMS, S3 lake, RDS, ECS/Fargate, ALB+WAF, API Gateway, OpenSearch, MWAA, CloudWatch, CloudTrail/GuardDuty/Config |

## 5. Key design decisions

| Decision | Rationale |
|---|---|
| Wide daily-signal table (`daily_signals`) as the analytical core | Each feed contributes a metric to the same `(date, region, disease)` row via partial upsert, which fixes the "inconsistent formats" problem at the boundary. |
| Global ML models with scale-free features (ratios, log-differences) | One model generalizes across regions of very different size and transfers to newly onboarded jurisdictions. |
| Rule-based risk engine on top of ML scores | Epidemiologists can audit why a level was assigned. Thresholds are policy, owned by the agency, not by the model. |
| Copilot provider chain: Claude → OpenAI → offline template | Keeps working during provider outages or in air-gapped deployments. Output is always grounded in cited facts and sources. |
| BFF with httpOnly cookie | Tokens are never exposed to browser JavaScript, which mitigates token theft through XSS. |
| Medallion lake with immutable bronze zone | Raw evidence can be reproduced, which supports data lineage and after-action review. |
