variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod"
  }
}

variable "region" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "az_count" {
  type    = number
  default = 3
}

variable "single_nat_gateway" {
  type    = bool
  default = false
}

variable "domain_name" {
  type = string
}

variable "certificate_arn" {
  type = string
}

variable "partner_api_domain" {
  type    = string
  default = ""
}

variable "partner_api_certificate_arn" {
  type    = string
  default = ""
}

variable "partner_mtls_truststore_uri" {
  type    = string
  default = ""
}

variable "image_tag" {
  type = string
}

variable "ses_sender" {
  type = string
}

variable "mapbox_public_token" {
  type    = string
  default = ""
}

variable "ops_emails" {
  type    = list(string)
  default = []
}

variable "api_cpu" {
  type    = number
  default = 1024
}

variable "api_memory" {
  type    = number
  default = 4096
}

variable "api_min_tasks" {
  type    = number
  default = 2
}

variable "api_max_tasks" {
  type    = number
  default = 20
}

variable "web_min_tasks" {
  type    = number
  default = 2
}

variable "web_max_tasks" {
  type    = number
  default = 10
}

variable "db_instance_class" {
  type    = string
  default = "db.r7g.large"
}

variable "db_multi_az" {
  type    = bool
  default = true
}

variable "db_read_replicas" {
  type    = number
  default = 0
}

variable "opensearch_instance_type" {
  type    = string
  default = "r7g.large.search"
}

variable "opensearch_instance_count" {
  type    = number
  default = 3
}

variable "opensearch_master_role_arn" {
  type = string
}

variable "mwaa_environment_class" {
  type    = string
  default = "mw1.medium"
}

variable "log_retention_days" {
  type    = number
  default = 365
}

variable "enable_account_security_services" {
  description = "GuardDuty / Security Hub / Config. Disable when an AWS Organization manages them centrally."
  type        = bool
  default     = true
}
