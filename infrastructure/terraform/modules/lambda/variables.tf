variable "name" {
  type = string
}

variable "source_root" {
  description = "Directory containing one sub-directory per function"
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "kms_key_arn" {
  type = string
}

variable "secrets_kms_key_arn" {
  type = string
}

variable "alerts_topic_arn" {
  type = string
}

variable "landing_bucket_name" {
  type = string
}

variable "landing_bucket_arn" {
  type = string
}

variable "app_url" {
  type = string
}
