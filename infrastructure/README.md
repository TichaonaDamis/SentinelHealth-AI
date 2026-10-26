# Infrastructure

```
infrastructure/
├── lambda/
│   ├── alert_fanout/        SNS → signed partner webhooks (HMAC-SHA256), DLQ
│   └── landing_validator/   S3 uploads → schema/PII checks → incoming/ or rejected/
└── terraform/
    ├── modules/             network, kms, storage, database, ecs, api_gateway, lambda,
    │                        opensearch, monitoring, security, mwaa
    ├── stack/               composes all modules into one deployable stack
    └── environments/
        ├── dev/             single NAT, small instances, no Multi-AZ DB
        └── prod/            per-AZ NAT, Multi-AZ RDS + replica, 3-node OpenSearch
```

Validate with `make tf-validate`; both environments pass `terraform validate`.
Deploy by following [docs/deployment-guide.md](../docs/deployment-guide.md).
