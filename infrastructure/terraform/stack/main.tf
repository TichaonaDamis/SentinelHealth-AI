# Composes all SentinelHealth modules into one deployable stack. Environments
# (environments/dev, environments/prod) call this with their own sizing.

data "aws_caller_identity" "current" {}

locals {
  name = "sentinel-${var.environment}"
}

module "kms" {
  source = "../modules/kms"
  name   = local.name
}

module "network" {
  source             = "../modules/network"
  name               = local.name
  region             = var.region
  cidr_block         = var.vpc_cidr
  az_count           = var.az_count
  single_nat_gateway = var.single_nat_gateway
  logs_kms_key_arn   = module.kms.logs_key_arn
  log_retention_days = var.log_retention_days
}

module "storage" {
  source        = "../modules/storage"
  name          = local.name
  account_id    = data.aws_caller_identity.current.account_id
  kms_key_arn   = module.kms.data_key_arn
  force_destroy = var.environment != "prod"
}

module "monitoring" {
  source                      = "../modules/monitoring"
  name                        = local.name
  region                      = var.region
  kms_key_arn                 = module.kms.data_key_arn
  ops_emails                  = var.ops_emails
  alb_arn_suffix              = module.ecs.alb_arn_suffix
  api_target_group_arn_suffix = module.ecs.api_target_group_arn_suffix
  db_instance_id              = module.database.instance_id
  ecs_cluster_name            = module.ecs.cluster_name
  api_service_name            = module.ecs.api_service_name
  api_log_group_name          = "/sentinel/${local.name}/api"
  dlq_name                    = "${local.name}-lambda-dlq"
}

module "ecs" {
  source                = "../modules/ecs"
  name                  = local.name
  environment           = var.environment
  vpc_id                = module.network.vpc_id
  vpc_cidr              = module.network.vpc_cidr
  public_subnet_ids     = module.network.public_subnet_ids
  private_subnet_ids    = module.network.private_subnet_ids
  domain_name           = var.domain_name
  certificate_arn       = var.certificate_arn
  image_tag             = var.image_tag
  data_kms_key_arn      = module.kms.data_key_arn
  logs_kms_key_arn      = module.kms.logs_key_arn
  secrets_kms_key_arn   = module.kms.secrets_key_arn
  models_bucket_arn     = module.storage.bucket_arns["models"]
  models_bucket_name    = module.storage.bucket_names["models"]
  alerts_topic_arn      = module.monitoring.alerts_topic_arn
  ses_sender            = var.ses_sender
  opensearch_endpoint   = module.opensearch.endpoint
  opensearch_domain_arn = module.opensearch.domain_arn
  mapbox_public_token   = var.mapbox_public_token
  api_cpu               = var.api_cpu
  api_memory            = var.api_memory
  api_min_tasks         = var.api_min_tasks
  api_max_tasks         = var.api_max_tasks
  web_min_tasks         = var.web_min_tasks
  web_max_tasks         = var.web_max_tasks
  log_retention_days    = var.log_retention_days
  deletion_protection   = var.environment == "prod"
}

module "database" {
  source                     = "../modules/database"
  name                       = local.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.isolated_subnet_ids
  allowed_security_group_ids = [module.ecs.service_security_group_ids["api"], module.mwaa.security_group_id]
  kms_key_arn                = module.kms.data_key_arn
  secrets_kms_key_arn        = module.kms.secrets_key_arn
  instance_class             = var.db_instance_class
  multi_az                   = var.db_multi_az
  read_replica_count         = var.db_read_replicas
  deletion_protection        = var.environment == "prod"
}

module "opensearch" {
  source                     = "../modules/opensearch"
  name                       = local.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.isolated_subnet_ids
  allowed_security_group_ids = [module.ecs.service_security_group_ids["api"], module.mwaa.security_group_id]
  client_role_arns           = [module.mwaa.execution_role_arn, "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.name}-api-task"]
  master_role_arn            = var.opensearch_master_role_arn
  kms_key_arn                = module.kms.data_key_arn
  logs_kms_key_arn           = module.kms.logs_key_arn
  instance_type              = var.opensearch_instance_type
  instance_count             = var.opensearch_instance_count
}

module "api_gateway" {
  source                = "../modules/api_gateway"
  name                  = local.name
  vpc_id                = module.network.vpc_id
  vpc_cidr              = module.network.vpc_cidr
  private_subnet_ids    = module.network.private_subnet_ids
  cloud_map_service_arn = module.ecs.api_discovery_service_arn
  custom_domain_name    = var.partner_api_domain
  certificate_arn       = var.partner_api_certificate_arn
  truststore_uri        = var.partner_mtls_truststore_uri
  logs_kms_key_arn      = module.kms.logs_key_arn
}

module "lambda" {
  source              = "../modules/lambda"
  name                = local.name
  source_root         = "${path.module}/../../lambda"
  vpc_id              = module.network.vpc_id
  private_subnet_ids  = module.network.private_subnet_ids
  kms_key_arn         = module.kms.data_key_arn
  secrets_kms_key_arn = module.kms.secrets_key_arn
  alerts_topic_arn    = module.monitoring.alerts_topic_arn
  landing_bucket_name = module.storage.bucket_names["landing"]
  landing_bucket_arn  = module.storage.bucket_arns["landing"]
  app_url             = "https://${var.domain_name}"
}

module "mwaa" {
  source             = "../modules/mwaa"
  name               = local.name
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  mwaa_bucket_arn    = module.storage.bucket_arns["mwaa"]
  data_bucket_arns   = [for k in ["raw", "lake", "landing", "models"] : module.storage.bucket_arns[k]]
  kms_key_arn        = module.kms.data_key_arn
  ecs_cluster_arn    = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:cluster/${local.name}"
  environment_class  = var.mwaa_environment_class
}

module "security" {
  source              = "../modules/security"
  name                = local.name
  region              = var.region
  audit_bucket_name   = module.storage.bucket_names["audit"]
  phi_bucket_arns     = [for k in ["raw", "lake", "landing"] : module.storage.bucket_arns[k]]
  logs_kms_key_arn    = module.kms.logs_key_arn
  enable_guardduty    = var.enable_account_security_services
  enable_security_hub = var.enable_account_security_services
  enable_config       = var.enable_account_security_services
}
