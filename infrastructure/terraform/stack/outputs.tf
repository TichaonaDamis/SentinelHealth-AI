output "alb_dns_name" {
  description = "Point the application DNS record (domain_name) at this ALB"
  value       = module.ecs.alb_dns_name
}

output "partner_api_endpoint" {
  value = module.api_gateway.api_endpoint
}

output "ecr_repositories" {
  value = module.ecs.ecr_repository_urls
}

output "ecs_cluster" {
  value = module.ecs.cluster_name
}

output "migrate_task_definition_arn" {
  value = module.ecs.migrate_task_definition_arn
}

output "private_subnet_ids" {
  value = module.network.private_subnet_ids
}

output "api_security_group_id" {
  value = module.ecs.service_security_group_ids["api"]
}

output "database_endpoint" {
  value = module.database.endpoint
}

output "database_master_secret_arn" {
  value = module.database.master_secret_arn
}

output "buckets" {
  value = module.storage.bucket_names
}

output "app_secret_arns" {
  description = "Populate these secrets before the first deployment (see docs/deployment-guide.md)"
  value       = module.ecs.secret_arns
}

output "mwaa_environment" {
  value = module.mwaa.environment_name
}
