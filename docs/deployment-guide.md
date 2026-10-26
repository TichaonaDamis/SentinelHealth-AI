# Deployment guide

## 1. Local development

### Option A: Docker Compose (full stack, recommended)

```bash
cp .env.example .env      # set SENTINEL_JWT_SECRET; optionally LLM keys and the Mapbox token
docker compose up --build # db (TimescaleDB+PostGIS+pgvector) → migrate+seed → api → web
open http://localhost:3000
```

The `migrate` service runs `alembic upgrade head` and seeds 400 days of synthetic surveillance data, demo users, the knowledge base, a month of alert history and forecasts. To add Airflow, run `docker compose --profile pipelines up` (UI at :8080).

### Option B: without Docker (SQLite)

```bash
python -m venv .venv && source .venv/bin/activate
make install            # backend + ml + frontend deps
make seed               # creates backend/sentinel.db
make api                # http://localhost:8000/docs
make web                # http://localhost:3000
```

### Demo accounts

All demo accounts use the password `ChangeMe!2026`, which `SENTINEL_SEED_PASSWORD` overrides.

| Email | Role | Scope |
|---|---|---|
| admin@sentinelhealth.dev | admin | national |
| epi@sentinelhealth.dev | epidemiologist | national |
| cdc.analyst@sentinelhealth.dev | cdc_analyst | national |
| tx.officer@sentinelhealth.dev | state_health_officer | TX |
| partner@sentinelhealth.dev | healthcare_partner | TX |
| viewer@sentinelhealth.dev | viewer | national |

Demo users are created only by the seed script. Never run it against production.

## 2. AWS deployment

### 2.1 Prerequisites (once per account)

1. An AWS account under a signed **BAA**, with AWS Organizations guardrails (SCPs) applied.
2. A Terraform state bucket (versioned, KMS-encrypted). The state uses native S3 locking (`use_lockfile`).
3. An ACM certificate for the app domain (and the partner API domain, if used).
4. A verified SES identity for the alert sender.
5. A GitHub OIDC provider and a deploy role trusted by `repo:<org>/sentinelhealth-ai:environment:{dev,prod}`.
6. An IAM role to act as OpenSearch admin (`opensearch_master_role_arn`).

### 2.2 Provision infrastructure

```bash
cd infrastructure/terraform/environments/dev
cp terraform.tfvars.example terraform.tfvars   # fill in values
terraform init -backend-config="bucket=<state-bucket>" -backend-config="region=us-east-1"
terraform plan -out plan.tfplan
terraform apply plan.tfplan
```

This creates:

- the VPC across 3 AZs, with endpoints and flow logs
- KMS keys
- six S3 buckets: raw (Object Lock), lake, landing, models, audit (Object Lock), and MWAA
- RDS PostgreSQL 16 (Multi-AZ in prod)
- the ECS cluster, ECR repositories, ALB and WAF
- API Gateway with a VPC link
- OpenSearch, MWAA, the Lambdas, and the SNS topics
- CloudWatch alarms and dashboard
- CloudTrail, GuardDuty, Security Hub, and AWS Config with the HIPAA conformance pack

### 2.3 Populate secrets (out of band, never in Terraform)

```bash
P=sentinel/sentinel-dev
aws secretsmanager put-secret-value --secret-id $P/jwt-secret --secret-string "$(openssl rand -base64 48)"
aws secretsmanager put-secret-value --secret-id $P/field-encryption-key \
  --secret-string "$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
aws secretsmanager put-secret-value --secret-id $P/database-url \
  --secret-string "postgresql+asyncpg://sentinel_api:<password>@<rds-endpoint>:5432/sentinel"
aws secretsmanager put-secret-value --secret-id $P/anthropic-api-key --secret-string "<key or empty>"
aws secretsmanager put-secret-value --secret-id $P/openai-api-key --secret-string "<key or empty>"
aws secretsmanager put-secret-value --secret-id $P/alert-endpoints \
  --secret-string '{"signing_key":"<random>","endpoints":[{"url":"https://hie.example.org/hooks/sentinel","min_level":"red"}]}'
```

The first deployment runs migrations with the master credentials from `database_master_secret_arn`. Migration `0003` creates the `sentinel_api`, `sentinel_etl` and `sentinel_readonly` roles; set their passwords (or enable IAM auth) and then update the `database-url` secret.

Airflow connections and variables go under `sentinel/<env>/airflow/connections/*` and `.../variables/*` (Secrets Manager backend).

### 2.4 Deploy the application (CI/CD)

`.github/workflows/cd.yml` runs on every push to `main` (deploys to dev) and on `v*` tags (deploys to prod, gated by environment approval):

1. Build arm64 images for the API and web, and an amd64 image for Airflow; push them to ECR (immutable tags = git SHA).
2. Run `terraform apply` with the new `image_tag`, which creates new task definitions.
3. Run the one-off **migrate** Fargate task (`alembic upgrade head`) and fail the deployment if it fails.
4. Wait for ECS services to stabilize. The deployment circuit breaker rolls back automatically on failed health checks.
5. Sync DAGs, `plugins.zip` and `requirements.txt` to the MWAA bucket.
6. Smoke test `/health` and `/ready`.

### 2.5 Models

The API loads the champion models from `s3://<models-bucket>/champion/` at start-up (`SENTINEL_MODEL_S3_URI`, checksum-verified). If they are missing, it uses the artifacts bundled in the image. The first champion is promoted by the `model_retraining` DAG; you can also upload `ml/artifacts/*` manually.

### 2.6 Post-deploy checklist

- [ ] Point DNS (Route 53 alias) at `alb_dns_name`. Point the partner domain at the API Gateway custom domain.
- [ ] Enable the Airflow DAGs and confirm a successful `ingest_public_sources` → `surveillance_pipeline` run.
- [ ] Confirm the CloudWatch alarm `surveillance-scan-stalled` is OK the next day.
- [ ] Create real users through the IdP and remove any demo users.
- [ ] Subscribe on-call to the ops SNS topic, and state distribution lists to the alerts topic. Add SSM parameters `/sentinel/distribution/<audience>/<state>`.

## 3. Operations runbook (abridged)

| Symptom | Check |
|---|---|
| No new alerts | `surveillance_pipeline` DAG status; `SurveillanceScans` metric; the `/ready` model versions |
| Alert storm | Data quality first: lineage view for the batch, then partner file rejects (`SentinelHealth/Landing` metrics). Adjust thresholds only through policy review. |
| Forecast intervals too narrow | Compare coverage in `forecasts` against actuals; retrain or recalibrate conformal quantiles |
| DLQ not empty | Partner webhook down. Inspect `alert-fanout` logs and re-drive the DLQ. |
| Database CPU high | Move dashboard reads to the replica; check `pg_stat_statements` |

## 4. Rollback

- **Application:** redeploy the previous image tag (`workflow_dispatch` with an older SHA), or let the ECS circuit breaker roll back on its own.
- **Database:** migrations are reversible (`alembic downgrade -1`). For data issues, use RDS point-in-time restore to a new instance.
- **Models:** copy `versions/<date>/` back to `champion/` and force a new ECS deployment.
