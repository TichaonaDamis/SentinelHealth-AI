# Amazon OpenSearch Service: hybrid (BM25 + k-NN) retrieval for the copilot knowledge base at
# national scale, and fast search over alerts / outbreak events. VPC-only, encrypted, FGAC enabled.

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

resource "aws_security_group" "this" {
  name        = "${var.name}-opensearch"
  description = "OpenSearch HTTPS from app tier"
  vpc_id      = var.vpc_id
  ingress {
    description     = "HTTPS from app tier"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = var.allowed_security_group_ids
  }
}

resource "aws_cloudwatch_log_group" "this" {
  for_each          = toset(["index-slow", "search-slow", "es-application", "audit"])
  name              = "/sentinel/${var.name}/opensearch/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.logs_kms_key_arn
}

resource "aws_cloudwatch_log_resource_policy" "this" {
  policy_name = "${var.name}-opensearch-logs"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "es.amazonaws.com" }
      Action    = ["logs:PutLogEvents", "logs:CreateLogStream"]
      Resource  = [for g in aws_cloudwatch_log_group.this : "${g.arn}:*"]
    }]
  })
}

resource "aws_opensearch_domain" "this" {
  domain_name    = "${var.name}-search"
  engine_version = var.engine_version

  cluster_config {
    instance_type            = var.instance_type
    instance_count           = var.instance_count
    zone_awareness_enabled   = var.instance_count > 1
    dedicated_master_enabled = var.dedicated_master
    dedicated_master_type    = var.dedicated_master ? "m7g.large.search" : null
    dedicated_master_count   = var.dedicated_master ? 3 : null
    dynamic "zone_awareness_config" {
      for_each = var.instance_count > 1 ? [1] : []
      content {
        availability_zone_count = min(var.instance_count, 3)
      }
    }
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.volume_size_gb
  }

  vpc_options {
    subnet_ids         = slice(var.subnet_ids, 0, min(var.instance_count, length(var.subnet_ids)))
    security_group_ids = [aws_security_group.this.id]
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = var.kms_key_arn
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-PFS-2023-10"
  }

  advanced_security_options {
    enabled                        = true
    anonymous_auth_enabled         = false
    internal_user_database_enabled = false
    master_user_options {
      master_user_arn = var.master_role_arn
    }
  }

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = var.client_role_arns }
      Action    = "es:ESHttp*"
      Resource  = "arn:aws:es:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:domain/${var.name}-search/*"
    }]
  })

  dynamic "log_publishing_options" {
    for_each = {
      INDEX_SLOW_LOGS     = "index-slow"
      SEARCH_SLOW_LOGS    = "search-slow"
      ES_APPLICATION_LOGS = "es-application"
      AUDIT_LOGS          = "audit"
    }
    content {
      log_type                 = log_publishing_options.key
      cloudwatch_log_group_arn = aws_cloudwatch_log_group.this[log_publishing_options.value].arn
    }
  }

  depends_on = [aws_cloudwatch_log_resource_policy.this]
}
