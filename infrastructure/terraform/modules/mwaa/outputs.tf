output "environment_name" {
  value = aws_mwaa_environment.this.name
}

output "execution_role_arn" {
  value = aws_iam_role.this.arn
}

output "security_group_id" {
  value = aws_security_group.this.id
}
