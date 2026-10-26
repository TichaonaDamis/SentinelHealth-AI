variable "name" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "domain_name" {
  description = "Public host name of the application, e.g. sentinel.health.example.gov"
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate for domain_name"
  type        = string
}

variable "image_tag" {
  type = string
}

variable "data_kms_key_arn" {
  type = string
}

variable "logs_kms_key_arn" {
  type = string
}

variable "secrets_kms_key_arn" {
  type = string
}

variable "models_bucket_arn" {
  type = string
}

variable "models_bucket_name" {
  type = string
}

variable "alb_logs_bucket" {
  description = "Bucket for ALB access logs (must allow the regional ELB principal); empty disables"
  type        = string
  default     = ""
}

variable "alerts_topic_arn" {
  type = string
}

variable "ses_sender" {
  type = string
}

variable "opensearch_endpoint" {
  type = string
}

variable "opensearch_domain_arn" {
  type = string
}

variable "mapbox_public_token" {
  description = "Public (pk.*) Mapbox token restricted to domain_name"
  type        = string
  default     = ""
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

variable "waf_rate_limit" {
  description = "Requests per 5 minutes per IP"
  type        = number
  default     = 2000
}

variable "log_retention_days" {
  type    = number
  default = 365
}

variable "deletion_protection" {
  type    = bool
  default = true
}
