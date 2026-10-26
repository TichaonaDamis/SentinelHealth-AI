# Product roadmap

## Phase 0: MVP foundation (this repository) ✅

- Multi-source daily signal model with lineage; ingestion API; CDC, WHO and HealthData.gov connectors; partner landing zone
- Anomaly ensemble (Isolation Forest, One-Class SVM, Autoencoder) with an EARS C2 baseline
- Outbreak classifier (High/Medium/Low) with calibration and TreeSHAP explanations
- 7/14/30-day forecasting (persistence, XGBoost, LSTM, Prophet) with conformal intervals and hospitalization/mortality risk
- HDBSCAN/DBSCAN hotspot detection with relative risk
- Green/Yellow/Orange/Red risk engine; de-duplicated, audience-routed alerts
- RAG copilot (Claude → OpenAI → offline) with hybrid search and citations
- Executive dashboard, alert triage, forecasts, model performance, audit log
- HIPAA-aligned AWS reference architecture in Terraform; CI/CD

## Phase 1: Pilot with one or two jurisdictions (months 0-4)

| Outcome | Work |
|---|---|
| Real-data validation | Retrospective validation on 3+ years of jurisdiction data and adjudicated outbreak line lists, with a report comparing against the current ESSENCE/EARS workflow |
| Identity | OIDC/SAML integration (Login.gov, Okta, Entra ID) with MFA; IdP groups mapped to roles |
| Data onboarding | Field-mapping UI for partner feeds; ELR (HL7 v2 ORU^R01) and eCR (FHIR eICR) parsers; NSSP ESSENCE API connector |
| Alert policy | Per-jurisdiction thresholds, quiet hours, escalation chains, on-call integration (PagerDuty / Opsgenie) |
| Feedback loop | Analyst adjudication (true signal, artifact, already known) captured on every alert and fed back into training and threshold tuning |
| Ops | SLOs (API 99.9%, scan freshness < 26 h), runbooks, game days |

## Phase 2: State-wide production (months 4-9)

- County → census-tract resolution; real polygon boundaries (TIGER/Line) in PostGIS; tract-level choropleths
- Space-time scan statistics (SaTScan-style Kulldorff scan) next to HDBSCAN, for cluster significance testing
- Genomic surveillance: lineage and variant tracking from sequencing results (`lab_reports.lineage`)
- Forecast hub compatibility: export in CDC FluSight / COVID-19 Forecast Hub formats, and ensemble with external models
- Copilot v2: tool use (query the warehouse, draft HAN messages for review), document ingestion from SharePoint and Drive, retrieval evaluation harness
- Mobile-friendly alert views; push notifications
- Accessibility audit (WCAG 2.2 AA) and Section 508 VPAT

## Phase 3: Multi-state / national (months 9-18)

- Multi-tenant SaaS: tenant isolation (schema- or database-per-tenant), per-tenant KMS keys, data-sharing agreements expressed as policy
- Federated analytics: jurisdictions keep record-level data and share only aggregates and model updates (federated learning for the classifier)
- National views for CDC analysts with cross-jurisdiction cluster linking
- Hospital capacity forecasting (beds, ICU, staffing), linked to the forecast engine
- Mobility and climate covariates (temperature and rainfall for dengue/vector-borne; school calendars for respiratory illness)
- FedRAMP Moderate authorization path; StateRAMP

## Phase 4: Global surveillance (18+ months)

- WHO IHR event-based surveillance: multilingual news and ProMED signal ingestion with LLM triage
- One Health: veterinary and agricultural signals, zoonotic risk
- Deployment kits for low-resource ministries of health (offline copilot, low-bandwidth UI, DHIS2 connector)
- Pandemic-preparedness scenario modelling (intervention what-ifs) on the forecasting stack

## Success metrics tracked per phase

| Metric | Target (pilot) | How measured |
|---|---|---|
| Detection lead time vs. traditional reporting | ≥ 5 days median | Event-level evaluation on adjudicated outbreaks (`early_detection` in metrics.json) |
| Alert precision (analyst-confirmed signals) | ≥ 40% at Orange+ | Alert adjudications in `fact_alerts` |
| Epidemiologist review time | −50% vs. baseline | Time-to-acknowledge; time to produce a sitrep |
| Surveillance coverage | +2 new feeds per quarter | Active sources in `ingestion_batches` |
| Forecast skill | > 0.2 vs. persistence at 14 days | Rolling backtest |
| Scale | 10M+ signals/day, < 2 s p95 API | Load tests, CloudWatch |
