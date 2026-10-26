terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
  # State in an encrypted, versioned S3 bucket with native S3 locking (create once per account).
  backend "s3" {
    key          = "sentinelhealth/prod/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "SentinelHealth-AI"
      Environment = "prod"
      ManagedBy   = "terraform"
      DataClass   = "PHI-limited"
    }
  }
}

module "sentinel" {
  source = "../../stack"

  environment                      = "prod"
  region                           = var.region
  vpc_cidr                         = var.vpc_cidr
  single_nat_gateway               = var.single_nat_gateway
  domain_name                      = var.domain_name
  certificate_arn                  = var.certificate_arn
  partner_api_domain               = var.partner_api_domain
  partner_api_certificate_arn      = var.partner_api_certificate_arn
  image_tag                        = var.image_tag
  ses_sender                       = var.ses_sender
  mapbox_public_token              = var.mapbox_public_token
  ops_emails                       = var.ops_emails
  opensearch_master_role_arn       = var.opensearch_master_role_arn
  api_min_tasks                    = var.api_min_tasks
  api_max_tasks                    = var.api_max_tasks
  web_min_tasks                    = var.web_min_tasks
  db_instance_class                = var.db_instance_class
  db_multi_az                      = var.db_multi_az
  db_read_replicas                 = var.db_read_replicas
  opensearch_instance_type         = var.opensearch_instance_type
  opensearch_instance_count        = var.opensearch_instance_count
  mwaa_environment_class           = var.mwaa_environment_class
  enable_account_security_services = var.enable_account_security_services
}

output "sentinel" {
  value = module.sentinel
}
