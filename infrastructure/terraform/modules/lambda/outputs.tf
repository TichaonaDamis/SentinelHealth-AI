output "alert_fanout_function" {
  value = aws_lambda_function.fanout.function_name
}

output "landing_validator_function" {
  value = aws_lambda_function.validator.function_name
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}
