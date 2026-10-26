# Event-driven functions: alert fan-out (SNS -> partner webhooks) and landing-zone validation (S3 -> S3).

data "archive_file" "fn" {
  for_each    = toset(["alert_fanout", "landing_validator"])
  type        = "zip"
  source_dir  = "${var.source_root}/${each.key}"
  output_path = "${path.module}/.build/${each.key}.zip"
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_security_group" "lambda" {
  name        = "${var.name}-lambda"
  description = "Lambda functions"
  vpc_id      = var.vpc_id
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-lambda-dlq"
  kms_master_key_id         = var.kms_key_arn
  message_retention_seconds = 1209600
}

resource "aws_secretsmanager_secret" "endpoints" {
  name       = "sentinel/${var.name}/alert-endpoints"
  kms_key_id = var.secrets_kms_key_arn
}

# ---- alert fan-out ------------------------------------------------------------------
resource "aws_iam_role" "fanout" {
  name               = "${var.name}-alert-fanout"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "fanout_vpc" {
  role       = aws_iam_role.fanout.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "fanout" {
  role = aws_iam_role.fanout.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = aws_secretsmanager_secret.endpoints.arn },
      { Effect = "Allow", Action = ["kms:Decrypt"], Resource = [var.secrets_kms_key_arn, var.kms_key_arn] },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.dlq.arn },
    ]
  })
}

resource "aws_lambda_function" "fanout" {
  function_name    = "${var.name}-alert-fanout"
  role             = aws_iam_role.fanout.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.fn["alert_fanout"].output_path
  source_code_hash = data.archive_file.fn["alert_fanout"].output_base64sha256
  timeout          = 60
  memory_size      = 256
  kms_key_arn      = var.kms_key_arn
  architectures    = ["arm64"]
  environment {
    variables = { ENDPOINTS_SECRET_ARN = aws_secretsmanager_secret.endpoints.arn, APP_URL = var.app_url }
  }
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }
  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }
  tracing_config {
    mode = "Active"
  }
}

resource "aws_lambda_permission" "sns" {
  statement_id  = "AllowSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fanout.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = var.alerts_topic_arn
}

resource "aws_sns_topic_subscription" "fanout" {
  topic_arn = var.alerts_topic_arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.fanout.arn
}

# ---- landing validator --------------------------------------------------------------
resource "aws_iam_role" "validator" {
  name               = "${var.name}-landing-validator"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "validator_vpc" {
  role       = aws_iam_role.validator.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "validator" {
  role = aws_iam_role.validator.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${var.landing_bucket_arn}/*" },
      { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = var.kms_key_arn },
      { Effect = "Allow", Action = ["cloudwatch:PutMetricData"], Resource = "*", Condition = { StringEquals = { "cloudwatch:namespace" = "SentinelHealth/Landing" } } },
    ]
  })
}

resource "aws_lambda_function" "validator" {
  function_name    = "${var.name}-landing-validator"
  role             = aws_iam_role.validator.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.fn["landing_validator"].output_path
  source_code_hash = data.archive_file.fn["landing_validator"].output_base64sha256
  timeout          = 120
  memory_size      = 512
  kms_key_arn      = var.kms_key_arn
  architectures    = ["arm64"]
  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }
  tracing_config {
    mode = "Active"
  }
}

resource "aws_lambda_permission" "s3" {
  statement_id  = "AllowS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.validator.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.landing_bucket_arn
}

resource "aws_s3_bucket_notification" "landing" {
  bucket = var.landing_bucket_name
  dynamic "lambda_function" {
    for_each = toset(["syndromic", "hospital", "pharmacy", "environment"])
    content {
      lambda_function_arn = aws_lambda_function.validator.arn
      events              = ["s3:ObjectCreated:*"]
      filter_prefix       = "${lambda_function.value}/uploads/"
    }
  }
  depends_on = [aws_lambda_permission.s3]
}
