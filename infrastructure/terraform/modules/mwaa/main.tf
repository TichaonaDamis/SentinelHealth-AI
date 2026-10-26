# Amazon Managed Workflows for Apache Airflow running the SentinelHealth DAGs.
# DAGs/plugins/requirements are synced to the mwaa bucket by the CD pipeline.

data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

resource "aws_security_group" "this" {
  name        = "${var.name}-mwaa"
  description = "MWAA workers and web server"
  vpc_id      = var.vpc_id
  ingress {
    description = "self"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "this" {
  name = "${var.name}-mwaa"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = ["airflow.amazonaws.com", "airflow-env.amazonaws.com"] }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "this" {
  role = aws_iam_role.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject*", "s3:GetBucket*", "s3:List*"], Resource = [var.mwaa_bucket_arn, "${var.mwaa_bucket_arn}/*"] },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject", "s3:CopyObject"],
      Resource = flatten([for b in var.data_bucket_arns : [b, "${b}/*"]]) },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:CreateLogGroup", "logs:PutLogEvents", "logs:GetLogEvents", "logs:GetLogRecord", "logs:GetLogGroupFields", "logs:GetQueryResults", "logs:DescribeLogGroups"],
      Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:airflow-${var.name}-*" },
      { Effect = "Allow", Action = ["cloudwatch:PutMetricData"], Resource = "*" },
      { Effect = "Allow", Action = ["sqs:ChangeMessageVisibility", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ReceiveMessage", "sqs:SendMessage"],
      Resource = "arn:aws:sqs:${data.aws_region.current.name}:*:airflow-celery-*" },
      { Effect = "Allow", Action = ["kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKey*", "kms:Encrypt"], Resource = [var.kms_key_arn] },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:sentinel/${var.name}/airflow/*" },
      { Effect = "Allow", Action = ["ecs:UpdateService"], Resource = "*", Condition = { StringEquals = { "ecs:cluster" = var.ecs_cluster_arn } } },
    ]
  })
}

resource "aws_mwaa_environment" "this" {
  name                            = "${var.name}-airflow"
  airflow_version                 = var.airflow_version
  environment_class               = var.environment_class
  max_workers                     = var.max_workers
  source_bucket_arn               = var.mwaa_bucket_arn
  dag_s3_path                     = "dags/"
  plugins_s3_path                 = "plugins.zip"
  requirements_s3_path            = "requirements.txt"
  execution_role_arn              = aws_iam_role.this.arn
  kms_key                         = var.kms_key_arn
  webserver_access_mode           = "PRIVATE_ONLY"
  weekly_maintenance_window_start = "SUN:05:00"

  airflow_configuration_options = {
    "secrets.backend"              = "airflow.providers.amazon.aws.secrets.secrets_manager.SecretsManagerBackend"
    "secrets.backend_kwargs"       = jsonencode({ connections_prefix = "sentinel/${var.name}/airflow/connections", variables_prefix = "sentinel/${var.name}/airflow/variables" })
    "core.default_task_retries"    = "2"
    "scheduler.catchup_by_default" = "False"
    "webserver.expose_config"      = "False"
  }

  network_configuration {
    security_group_ids = [aws_security_group.this.id]
    subnet_ids         = slice(var.private_subnet_ids, 0, 2)
  }

  logging_configuration {
    dag_processing_logs {
      enabled   = true
      log_level = "INFO"
    }
    scheduler_logs {
      enabled   = true
      log_level = "INFO"
    }
    task_logs {
      enabled   = true
      log_level = "INFO"
    }
    webserver_logs {
      enabled   = true
      log_level = "WARNING"
    }
    worker_logs {
      enabled   = true
      log_level = "INFO"
    }
  }
}
