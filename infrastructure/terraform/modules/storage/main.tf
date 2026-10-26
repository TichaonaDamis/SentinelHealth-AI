# S3 data lake and supporting buckets. Every bucket: SSE-KMS, versioning, public access
# blocked, TLS-only bucket policy, server access logging. Raw (bronze) and audit buckets use
# Object Lock so evidence cannot be altered (HIPAA requires 6-year documentation retention).

locals {
  buckets = {
    raw = {
      purpose        = "Bronze zone: immutable raw payloads exactly as received"
      object_lock    = { mode = "GOVERNANCE", days = var.raw_retention_days }
      expire_days    = null
      transition_ias = 90
    }
    lake = {
      purpose        = "Silver/gold/quarantine zones (normalised parquet)"
      object_lock    = null
      expire_days    = null
      transition_ias = 180
    }
    landing = {
      purpose        = "Partner SFTP/S3 drop zone"
      object_lock    = null
      expire_days    = 30
      transition_ias = null
    }
    models = {
      purpose        = "Model registry (versions/ and champion/)"
      object_lock    = null
      expire_days    = null
      transition_ias = null
    }
    audit = {
      purpose        = "CloudTrail and application audit log archive"
      object_lock    = { mode = "COMPLIANCE", days = var.audit_retention_days }
      expire_days    = null
      transition_ias = 30
    }
    mwaa = {
      purpose        = "Airflow DAGs, plugins and requirements"
      object_lock    = null
      expire_days    = null
      transition_ias = null
    }
  }
}

resource "aws_s3_bucket" "access_logs" {
  bucket        = "${var.name}-access-logs-${var.account_id}"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # S3 server access logging does not support SSE-KMS targets
    }
  }
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket                  = aws_s3_bucket.access_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    expiration {
      days = 400
    }
  }
}

resource "aws_s3_bucket" "this" {
  for_each            = local.buckets
  bucket              = "${var.name}-${each.key}-${var.account_id}"
  object_lock_enabled = each.value.object_lock != null
  force_destroy       = var.force_destroy && each.value.object_lock == null
  tags                = { Purpose = each.value.purpose }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "this" {
  for_each = { for k, v in local.buckets : k => v if v.object_lock != null }
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    default_retention {
      mode = each.value.object_lock.mode
      days = each.value.object_lock.days
    }
  }
  depends_on = [aws_s3_bucket_versioning.this]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_logging" "this" {
  for_each      = aws_s3_bucket.this
  bucket        = each.value.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "${each.key}/"
}

# Service-principal statements appended to individual bucket policies (audit bucket: CloudTrail, AWS Config).
locals {
  service_statements = [
    { bucket = "audit", policy = {
      Sid       = "CloudTrailAclCheck"
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
      Action    = "s3:GetBucketAcl"
      Resource  = aws_s3_bucket.this["audit"].arn
    } },
    { bucket = "audit", policy = {
      Sid       = "CloudTrailWrite"
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
      Action    = "s3:PutObject"
      Resource  = "${aws_s3_bucket.this["audit"].arn}/cloudtrail/AWSLogs/${var.account_id}/*"
    } },
    { bucket = "audit", policy = {
      Sid       = "AWSConfigBucketCheck"
      Effect    = "Allow"
      Principal = { Service = "config.amazonaws.com" }
      Action    = ["s3:GetBucketAcl", "s3:ListBucket"]
      Resource  = aws_s3_bucket.this["audit"].arn
    } },
    { bucket = "audit", policy = {
      Sid       = "AWSConfigWrite"
      Effect    = "Allow"
      Principal = { Service = "config.amazonaws.com" }
      Action    = "s3:PutObject"
      Resource  = "${aws_s3_bucket.this["audit"].arn}/config/AWSLogs/${var.account_id}/Config/*"
    } },
  ]
}

resource "aws_s3_bucket_policy" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [each.value.arn, "${each.value.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "DenyUnencryptedUploads"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${each.value.arn}/*"
        Condition = { StringNotEqualsIfExists = { "s3:x-amz-server-side-encryption" = "aws:kms" }, Null = { "s3:x-amz-server-side-encryption" = "false" } }
      }],
      [for stmt in local.service_statements : stmt.policy if stmt.bucket == each.key]
    )
  })
  depends_on = [aws_s3_bucket_public_access_block.this]
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = { for k, v in local.buckets : k => v if v.expire_days != null || v.transition_ias != null }
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    id     = "tiering"
    status = "Enabled"
    filter {}
    dynamic "transition" {
      for_each = each.value.transition_ias == null ? [] : [each.value.transition_ias]
      content {
        days          = transition.value
        storage_class = "STANDARD_IA"
      }
    }
    dynamic "expiration" {
      for_each = each.value.expire_days == null ? [] : [each.value.expire_days]
      content {
        days = expiration.value
      }
    }
    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}
