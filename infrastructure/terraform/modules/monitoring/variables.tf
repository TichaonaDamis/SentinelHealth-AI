variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "ops_emails" {
  type    = list(string)
  default = []
}

variable "alb_arn_suffix" {
  type = string
}

variable "api_target_group_arn_suffix" {
  type = string
}

variable "db_instance_id" {
  type = string
}

variable "ecs_cluster_name" {
  type = string
}

variable "api_service_name" {
  type = string
}

variable "api_log_group_name" {
  type = string
}

variable "dlq_name" {
  type = string
}
