variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "allowed_security_group_ids" {
  type = list(string)
}

variable "client_role_arns" {
  description = "IAM roles allowed to call the domain (API task role, Airflow role)"
  type        = list(string)
}

variable "master_role_arn" {
  description = "IAM role mapped to the OpenSearch security plugin admin"
  type        = string
}

variable "kms_key_arn" {
  type = string
}

variable "logs_kms_key_arn" {
  type = string
}

variable "engine_version" {
  type    = string
  default = "OpenSearch_2.17"
}

variable "instance_type" {
  type    = string
  default = "r7g.large.search"
}

variable "instance_count" {
  type    = number
  default = 3
}

variable "dedicated_master" {
  type    = bool
  default = false
}

variable "volume_size_gb" {
  type    = number
  default = 100
}

variable "log_retention_days" {
  type    = number
  default = 365
}
