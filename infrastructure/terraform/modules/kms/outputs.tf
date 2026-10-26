output "data_key_arn" {
  value = aws_kms_key.this["data"].arn
}

output "logs_key_arn" {
  value = aws_kms_key.this["logs"].arn
}

output "secrets_key_arn" {
  value = aws_kms_key.this["secrets"].arn
}
