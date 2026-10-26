variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "mwaa_bucket_arn" {
  type = string
}

variable "data_bucket_arns" {
  description = "Lake, raw, landing and model buckets the DAGs read/write"
  type        = list(string)
}

variable "kms_key_arn" {
  type = string
}

variable "ecs_cluster_arn" {
  type = string
}

variable "airflow_version" {
  type    = string
  default = "2.10.3"
}

variable "environment_class" {
  type    = string
  default = "mw1.medium"
}

variable "max_workers" {
  type    = number
  default = 10
}
