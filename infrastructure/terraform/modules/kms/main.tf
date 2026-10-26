# Customer-managed KMS keys (encryption at rest). Separate keys per data class let us
# revoke or audit access independently: PHI-bearing data, logs, and application secrets.

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  keys = {
    data    = "RDS, S3 data lake, OpenSearch, backups (PHI-bearing)"
    logs    = "CloudWatch Logs, CloudTrail, VPC flow logs"
    secrets = "Secrets Manager and SSM parameters"
  }
}

locals {
  service_statements = [
    {
      key = "logs"
      policy = {
        Sid       = "CloudWatchLogsAndCloudTrail"
        Effect    = "Allow"
        Principal = { Service = ["logs.${data.aws_region.current.name}.amazonaws.com", "cloudtrail.amazonaws.com"] }
        Action    = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
      }
    },
  ]
}

resource "aws_kms_key" "this" {
  for_each                = local.keys
  description             = "SentinelHealth ${var.name} - ${each.value}"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      }],
      [for stmt in local.service_statements : stmt.policy if stmt.key == each.key]
    )
  })
  tags = { DataClass = each.key }
}

resource "aws_kms_alias" "this" {
  for_each      = aws_kms_key.this
  name          = "alias/sentinel-${var.name}-${each.key}"
  target_key_id = each.value.key_id
}
