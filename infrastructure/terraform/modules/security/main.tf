# Account security baseline: CloudTrail (all regions, log file validation, data events on PHI
# buckets), GuardDuty, Security Hub, and AWS Config with the HIPAA Security operational
# best-practices conformance pack for continuous compliance evidence.

data "aws_caller_identity" "current" {}

resource "aws_cloudwatch_log_group" "trail" {
  name              = "/sentinel/${var.name}/cloudtrail"
  retention_in_days = 365
  kms_key_id        = var.logs_kms_key_arn
}

resource "aws_iam_role" "trail" {
  name = "${var.name}-cloudtrail-logs"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "cloudtrail.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "trail" {
  role = aws_iam_role.trail.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.trail.arn}:*" }]
  })
}

resource "aws_cloudtrail" "this" {
  name                          = "${var.name}-trail"
  s3_bucket_name                = var.audit_bucket_name
  s3_key_prefix                 = "cloudtrail"
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  kms_key_id                    = var.logs_kms_key_arn
  cloud_watch_logs_group_arn    = "${aws_cloudwatch_log_group.trail.arn}:*"
  cloud_watch_logs_role_arn     = aws_iam_role.trail.arn

  event_selector {
    read_write_type           = "All"
    include_management_events = true
    data_resource {
      type   = "AWS::S3::Object"
      values = [for arn in var.phi_bucket_arns : "${arn}/"]
    }
  }
}

resource "aws_guardduty_detector" "this" {
  count  = var.enable_guardduty ? 1 : 0
  enable = true
}

resource "aws_guardduty_detector_feature" "this" {
  for_each    = var.enable_guardduty ? toset(["S3_DATA_EVENTS", "RDS_LOGIN_EVENTS", "RUNTIME_MONITORING", "LAMBDA_NETWORK_LOGS"]) : toset([])
  detector_id = aws_guardduty_detector.this[0].id
  name        = each.value
  status      = "ENABLED"
}

resource "aws_securityhub_account" "this" {
  count = var.enable_security_hub ? 1 : 0
}

resource "aws_securityhub_standards_subscription" "fsbp" {
  count         = var.enable_security_hub ? 1 : 0
  standards_arn = "arn:aws:securityhub:${var.region}::standards/aws-foundational-security-best-practices/v/1.0.0"
  depends_on    = [aws_securityhub_account.this]
}

# --- AWS Config + HIPAA conformance pack ---------------------------------------------------
resource "aws_iam_role" "config" {
  count = var.enable_config ? 1 : 0
  name  = "${var.name}-aws-config"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "config.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "config" {
  count      = var.enable_config ? 1 : 0
  role       = aws_iam_role.config[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_config_configuration_recorder" "this" {
  count    = var.enable_config ? 1 : 0
  name     = "${var.name}-recorder"
  role_arn = aws_iam_role.config[0].arn
  recording_group {
    all_supported                 = true
    include_global_resource_types = true
  }
}

resource "aws_config_delivery_channel" "this" {
  count          = var.enable_config ? 1 : 0
  name           = "${var.name}-config"
  s3_bucket_name = var.audit_bucket_name
  s3_key_prefix  = "config"
  depends_on     = [aws_config_configuration_recorder.this]
}

resource "aws_config_configuration_recorder_status" "this" {
  count      = var.enable_config ? 1 : 0
  name       = aws_config_configuration_recorder.this[0].name
  is_enabled = true
  depends_on = [aws_config_delivery_channel.this]
}

resource "aws_config_conformance_pack" "hipaa" {
  count         = var.enable_config ? 1 : 0
  name          = "${var.name}-hipaa-security"
  template_body = file("${path.module}/hipaa-conformance-pack.yaml")
  depends_on    = [aws_config_configuration_recorder_status.this]
}
