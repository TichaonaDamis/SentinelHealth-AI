output "endpoint" {
  value = aws_db_instance.this.address
}

output "port" {
  value = aws_db_instance.this.port
}

output "master_secret_arn" {
  value = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "security_group_id" {
  value = aws_security_group.db.id
}

output "instance_id" {
  value = aws_db_instance.this.identifier
}

output "resource_id" {
  value = aws_db_instance.this.resource_id
}
