output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "ops_topic_arn" {
  value = aws_sns_topic.ops.arn
}
