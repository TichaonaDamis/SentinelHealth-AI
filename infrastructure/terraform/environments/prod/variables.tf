variable "region" {
  type    = string
  default = "us-east-1"
}

variable "vpc_cidr" {
  type = string
}

variable "single_nat_gateway" {
  type = bool
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

variable "opensearch_master_role_arn" {
  type = string
}

variable "api_min_tasks" {
  type = number
}

variable "api_max_tasks" {
  type = number
}

variable "web_min_tasks" {
  type = number
}

variable "db_instance_class" {
  type = string
}

variable "db_multi_az" {
  type = bool
}

variable "db_read_replicas" {
  type = number
}

variable "opensearch_instance_type" {
  type = string
}

variable "opensearch_instance_count" {
  type = number
}

variable "mwaa_environment_class" {
  type = string
}

variable "enable_account_security_services" {
  type    = bool
  default = true
}
