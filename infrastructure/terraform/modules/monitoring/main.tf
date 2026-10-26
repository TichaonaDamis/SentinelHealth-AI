# CloudWatch alarms, operations dashboard and the alerts SNS topic used by the application.

resource "aws_sns_topic" "ops" {
  name              = "${var.name}-ops-alarms"
  kms_master_key_id = var.kms_key_arn
}

resource "aws_sns_topic_subscription" "ops_email" {
  for_each  = toset(var.ops_emails)
  topic_arn = aws_sns_topic.ops.arn
  protocol  = "email"
  endpoint  = each.value
}

# Public-health alerts published by the API (consumed by SMS subscribers and the fan-out Lambda).
resource "aws_sns_topic" "alerts" {
  name              = "${var.name}-public-health-alerts"
  kms_master_key_id = var.kms_key_arn
}

locals {
  alarms = {
    api_5xx = {
      namespace = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", stat = "Sum", threshold = 10, op = "GreaterThanThreshold",
      dims      = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.api_target_group_arn_suffix }, desc = "API returning 5xx errors"
    }
    api_latency_p95 = {
      namespace = "AWS/ApplicationELB", metric = "TargetResponseTime", stat = "p95", threshold = 2, op = "GreaterThanThreshold",
      dims      = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.api_target_group_arn_suffix }, desc = "API p95 latency above 2s"
    }
    rds_cpu = {
      namespace = "AWS/RDS", metric = "CPUUtilization", stat = "Average", threshold = 80, op = "GreaterThanThreshold",
      dims      = { DBInstanceIdentifier = var.db_instance_id }, desc = "RDS CPU above 80%"
    }
    rds_storage = {
      namespace = "AWS/RDS", metric = "FreeStorageSpace", stat = "Minimum", threshold = 20 * 1024 * 1024 * 1024, op = "LessThanThreshold",
      dims      = { DBInstanceIdentifier = var.db_instance_id }, desc = "RDS free storage below 20 GiB"
    }
    ecs_api_cpu = {
      namespace = "AWS/ECS", metric = "CPUUtilization", stat = "Average", threshold = 85, op = "GreaterThanThreshold",
      dims      = { ClusterName = var.ecs_cluster_name, ServiceName = var.api_service_name }, desc = "API service CPU saturated"
    }
    lambda_dlq = {
      namespace = "AWS/SQS", metric = "ApproximateNumberOfMessagesVisible", stat = "Maximum", threshold = 0, op = "GreaterThanThreshold",
      dims      = { QueueName = var.dlq_name }, desc = "Alert deliveries failing (DLQ not empty)"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each            = local.alarms
  alarm_name          = "${var.name}-${each.key}"
  alarm_description   = each.value.desc
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  extended_statistic  = startswith(each.value.stat, "p") ? each.value.stat : null
  statistic           = startswith(each.value.stat, "p") ? null : each.value.stat
  period              = 300
  evaluation_periods  = 2
  threshold           = each.value.threshold
  comparison_operator = each.value.op
  dimensions          = each.value.dims
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops.arn]
  ok_actions          = [aws_sns_topic.ops.arn]
}

# Business-level alarm: no surveillance scan has produced output in 26 hours (pipeline stalled).
resource "aws_cloudwatch_log_metric_filter" "scan_completed" {
  name           = "${var.name}-scan-completed"
  log_group_name = var.api_log_group_name
  pattern        = "{ $.type = \"audit\" && $.action = \"analytics:run\" && $.status_code = 200 }"
  metric_transformation {
    name      = "SurveillanceScans"
    namespace = "SentinelHealth"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "scan_stalled" {
  alarm_name          = "${var.name}-surveillance-scan-stalled"
  alarm_description   = "No successful surveillance scan in 26h - outbreak detection is not running"
  namespace           = "SentinelHealth"
  metric_name         = "SurveillanceScans"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 26
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.ops.arn]
}

resource "aws_cloudwatch_dashboard" "ops" {
  dashboard_name = "${var.name}-operations"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title = "API requests & errors", region = var.region, stat = "Sum", period = 300
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.api_target_group_arn_suffix],
            [".", "HTTPCode_Target_5XX_Count", ".", ".", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title = "API latency (p50/p95)", region = var.region, period = 300
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.api_target_group_arn_suffix, { stat = "p50" }],
            ["...", { stat = "p95" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title = "RDS", region = var.region, stat = "Average", period = 300
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_id],
            [".", "DatabaseConnections", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title = "Surveillance scans & landing files", region = var.region, stat = "Sum", period = 3600
          metrics = [
            ["SentinelHealth", "SurveillanceScans"],
            ["SentinelHealth/Landing", "FilesAccepted", "Feed", "syndromic"],
            ["SentinelHealth/Landing", "FilesRejected", "Feed", "syndromic"],
          ]
        }
      },
    ]
  })
}
