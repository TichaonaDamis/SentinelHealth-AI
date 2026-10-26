# Security model

SentinelHealth handles surveillance data that may include protected health information (PHI), such as de-identified line lists with pseudonymous references. It is designed against the **HIPAA Security Rule** safeguards and maps to NIST SP 800-53 controls commonly used for FedRAMP / state ATOs.

> HIPAA compliance is a property of an organization's whole program (policies, BAAs, training, risk analysis), not of software alone. This document describes the technical controls the platform provides.

## 1. Data classification & minimization

| Class | Examples | Handling |
|---|---|---|
| Aggregate surveillance | `daily_signals`, forecasts, alerts | Default working set. All analytics and the copilot use only this class. |
| Limited line list | `case_reports` (age group, tract centroid, onset date) | No names, addresses or DOB accepted. The landing validator rejects files with direct-identifier columns. Coordinates are census-tract centroids. Row-level security applies by jurisdiction. |
| Pseudonymous identifiers | `case_reports.patient_ref` | Encrypted at the application layer (Fernet: AES-128-CBC + HMAC-SHA256) on top of RDS encryption. The key comes from Secrets Manager / KMS. |
| Raw partner payloads | S3 bronze zone | KMS-encrypted, Object Lock, access limited to the ETL role. CloudTrail records S3 data events. |

## 2. HIPAA Security Rule mapping

| Safeguard (45 CFR §164.312) | Control in SentinelHealth | Where |
|---|---|---|
| Access control: unique user ID (a)(2)(i) | Individual accounts, UUID subject in JWT, no shared users | `models.User`, `core/security.py` |
| Access control: emergency access (a)(2)(ii) | Break-glass admin role in the IdP, audited | IdP + audit log |
| Access control: automatic logoff (a)(2)(iii) | 30-minute token TTL; session cookie expires with the token | `access_token_ttl_minutes`, BFF cookie `maxAge` |
| Encryption/decryption (a)(2)(iv) | KMS CMKs for RDS, S3, OpenSearch, Logs, Secrets, ECR; field-level encryption for identifiers | `modules/kms`, `EncryptedString` |
| Audit controls (b) | Every API request logged (user, role, action, resource, IP, status, request ID), including denials and failed logins. Append-only table (trigger) mirrored to CloudWatch → S3 Object Lock (6 years). pgaudit for DDL/role changes. CloudTrail with log-file validation. | `core/audit.py`, migration 0001, `modules/security` |
| Integrity (c)(1) | Lineage batches with SHA-256 checksums, immutable bronze zone, model artifact checksums verified at load, S3 versioning | `IngestionBatch`, `lake.py`, `registry.py` |
| Person/entity authentication (d) | OIDC/SAML IdP with MFA in production; scrypt password hashing for the built-in fallback; password policy | `core/security.py`, `UserCreate` validator |
| Transmission security (e)(1) | TLS 1.2+ everywhere: ALB TLS 1.3 policy, HSTS, `rds.force_ssl=1`, OpenSearch TLS 1.2 PFS, API Gateway TLS 1.2 + optional partner mTLS, VPC endpoints for AWS APIs | Terraform modules, `SecurityHeadersMiddleware` |

## 3. Access control model

- **RBAC:** six roles, mapped to permissions (see [API design](api/README.md#role--permission-matrix)). Every endpoint declares its permission with `require(Perm.X)`, and denials are audited as `denied:<perm>`.
- **ABAC (jurisdiction):** state-scoped roles are filtered to their state in every query (`Principal.effective_state`). Requests for other states return `403`. Partners can submit data only for their own jurisdiction.
- **Database least privilege:** `sentinel_api` cannot run DDL and can only INSERT into `audit_logs`. `sentinel_etl` cannot read users or audit logs. `sentinel_readonly` sees only the warehouse. Row-level security on `case_reports` is keyed to `app.jurisdiction`.
- **Infrastructure least privilege:** each ECS task, Lambda and MWAA role grants only the actions it needs on named resources. Deployments use GitHub OIDC, with no long-lived AWS keys.

## 4. Application security

| Threat | Mitigation |
|---|---|
| XSS / token theft | Tokens live only in `httpOnly; Secure; SameSite=Strict` cookies (BFF pattern). Strict CSP, `X-Frame-Options: DENY`, `nosniff`, no `dangerouslySetInnerHTML` (the copilot markdown renderer builds React nodes). |
| CSRF | SameSite=Strict cookie; state-changing calls require JSON bodies through the BFF. |
| Injection | SQLAlchemy parameterized queries throughout; Pydantic validation with bounds on every input; WAF SQLi and common rule sets. |
| Brute force / abuse | WAF rate-based rule, API Gateway throttling for partners, failed logins audited (alarm on spikes). |
| Path traversal in proxy | BFF rejects `..` and encoded path separators. |
| Prompt injection via knowledge docs | Only `copilot:manage` roles can add documents. The system prompt treats sources as data. Outputs are cited and PHI-scrubbed, and the copilot has no tool or write access. |
| Supply chain | Pinned dependencies, Dependabot, pip-audit and npm audit, Trivy image scan, Checkov IaC scan, gitleaks; immutable ECR tags with scan-on-push. |
| Container hardening | Non-root UID 10001, read-only root filesystem (API), all Linux capabilities dropped, minimal slim/alpine bases. |

## 5. Data lineage

Every value is traceable end to end:

`daily_signals.batch_id` → `ingestion_batches` (source, pipeline run ID, submitter, checksum, `source_uri` of the bronze object) → immutable S3 raw payload.

`GET /lineage/signal?disease=…&region_id=…&observed_on=…` answers "where did this number come from?". Outbreak events store the model method and explanation; forecasts store the model and artifact version.

## 6. Monitoring & incident response

- GuardDuty (S3, RDS login, runtime, Lambda network), Security Hub (AWS FSBP), and AWS Config with the HIPAA conformance pack, which gives continuous compliance evidence.
- CloudWatch alarms on API 5xx and latency, RDS saturation, a stalled surveillance scan (no scan in 26 hours), and a non-empty alert-delivery DLQ.
- Audit-log retention is 6 years (S3 Object Lock, COMPLIANCE mode).
- Backups: RDS PITR for 35 days, Multi-AZ, cross-region snapshot copy (recommended for prod). RPO ≤ 5 minutes, RTO ≤ 1 hour.

## 7. Production checklist

- [ ] Sign a BAA with AWS. Use only HIPAA-eligible services (all services used here are on AWS's eligible list).
- [ ] Sign BAA / zero-retention terms with LLM providers, or keep the copilot in aggregate-only mode (the default).
- [ ] Integrate the IdP (OIDC) with MFA, and map IdP groups to roles.
- [ ] Generate `SENTINEL_JWT_SECRET` (≥ 32 bytes) and `SENTINEL_FIELD_ENCRYPTION_KEY` in Secrets Manager; rotate them on a schedule.
- [ ] Restrict the Mapbox public token to the production domain.
- [ ] Pen test and complete the risk analysis (§164.308(a)(1)) before go-live.
