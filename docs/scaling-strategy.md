# MVP → enterprise scaling strategy

## Stage overview

| Dimension | MVP (one jurisdiction) | Growth (one state) | Enterprise / national |
|---|---|---|---|
| Data volume | ~100k signal rows/yr | ~5M rows/yr; ~10M line-list rows | 25M+ signal rows/yr; 500M+ line-list rows; millions of lab results/day |
| Database | Single RDS (Multi-AZ) | + read replica, larger instance, partitioned `case_reports` | Timescale Cloud or Aurora PostgreSQL + Redshift/Athena for the warehouse; per-tenant schemas |
| Compute | 2 API tasks, 1 web task | Autoscaling 2-20 tasks | Autoscaling 3-40+ tasks per region; dedicated scoring workers |
| Pipelines | MWAA small | MWAA medium; parallel per-source tasks | MWAA large + EMR Serverless / Glue Spark for national backfills; Kinesis for streaming ELR |
| Analytics | Scan over a 90-day panel in-request | Scan triggered by Airflow per state, in parallel | Event-driven scoring on ingest (SQS → workers) and nightly full scans |
| Search / RAG | pgvector in Postgres | OpenSearch (3 nodes) | OpenSearch multi-AZ with dedicated masters and UltraWarm |
| Tenancy | Single-tenant | Single-tenant per state | Multi-tenant SaaS with tenant-scoped KMS keys and RLS |
| Ops | Business-hours | 24×7 on-call, SLOs | Multi-region active/passive, DR drills, FedRAMP |

## 1. Data tier

- **Time-series partitioning.** Hypertables (TimescaleDB) or BRIN-indexed tables keep queries bounded by date. At national scale, partition `case_reports` and `lab_reports` monthly with `pg_partman` and compress chunks older than 180 days.
- **Read/write separation.** Ingestion and alerting write to the primary. The dashboard, copilot facts and warehouse reads go to replicas. Use RDS Proxy for connection pooling once there are many tasks.
- **Warehouse offload.** When analyst workloads compete with OLTP, export the `warehouse` schema nightly to S3 (Parquet, partitioned by `mmwr_year/mmwr_week/state`) and query it with Athena or Redshift Serverless. The star schema carries over unchanged.
- **Data lake as the system of record.** The bronze and silver zones let any derived table be rebuilt, which matters as transforms evolve.

## 2. Compute & ML serving

- **Stateless API.** Horizontal scaling on CPU (target 60%) and on ALB request count. Models are loaded once per worker; the largest artifact is about 3 MB.
- **Scoring cost.** One national scan is O(regions × diseases × 90 days) for feature building plus a handful of tree-model predictions, which takes seconds per state. At county scale nationally (~60k series), shard the scan by state across SQS workers and write events idempotently.
- **Forecast fan-out.** Forecasts are precomputed nightly for every series (`surveillance_pipeline.forecast_all`), and the dashboard reads the stored rows. On-demand forecasts are only for drill-down.
- **GPU** is only needed for LSTM/autoencoder retraining on very large panels. Use SageMaker training jobs from the retraining DAG; serving stays on CPU.

## 3. Ingestion

- **Batch → streaming.** Electronic lab reports (HL7 v2) and eCR arrive continuously. Add a Kinesis Data Streams → Lambda/Flink path that writes the same canonical records and lineage batches as the batch path.
- **Back-pressure & quarantine.** Partner surges land in S3 first, so the API is never the bottleneck. Per-partner throttling happens at API Gateway.
- **Schema registry.** Version partner mappings, and treat breaking upstream changes as quarantined batches, not silent nulls.

## 4. Multi-tenancy (SaaS)

| Model | When | Notes |
|---|---|---|
| Account-per-tenant (silo) | State agencies with strict data-sovereignty requirements | Same Terraform stack per AWS account through Organizations/Control Tower. Simplest compliance story. |
| Schema-per-tenant (bridge) | Many small counties | One cluster; `search_path` per request; per-tenant KMS data keys for field encryption |
| Row-level (pool) | Aggregate-only national views | RLS on `jurisdiction`, the same pattern as `case_reports_jurisdiction` |

Cross-tenant sharing (for example, state → CDC) is an explicit, audited export of aggregates, governed by data-use agreements.

## 5. Reliability

- **Multi-AZ** for RDS, OpenSearch, ECS and NAT. **Cross-region** DR with RDS snapshot copy, S3 replication of raw/models/audit, and the infrastructure re-created from Terraform in the DR region (RTO ≤ 4 h at enterprise tier, ≤ 1 h with a warm standby).
- **Graceful degradation:** model artifacts fall back to heuristics, the copilot falls back across providers, and notifications fall back to in-app delivery when a channel is down.
- **SLOs:** API availability 99.9%; alert latency from ingest to notification < 1 h; scan freshness < 26 h. Burn-rate alarms are configured in CloudWatch.

## 6. Cost levers

- Graviton (arm64) Fargate tasks and RDS r7g instances.
- Single NAT gateway in dev, S3 Intelligent-Tiering for the lake, and lifecycle to Standard-IA after 90-180 days.
- OpenSearch is optional below about 50k knowledge chunks, because pgvector handles the MVP.
- Precomputed forecasts avoid repeated on-demand model runs.

## 7. Organizational scaling

- **Model governance:** a model card per release, a champion/challenger gate, and an analyst feedback loop. Thresholds are owned by an epidemiology policy board.
- **Platform team:** paved-road modules (the `stack`), golden Docker images, and shared observability.
- **Customer onboarding playbook:** data-sharing agreement → feed mapping → 4-week shadow mode (alerts visible, not sent) → go-live.
