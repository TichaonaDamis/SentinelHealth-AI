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

variable "kms_key_arn" {
  type = string
}

variable "secrets_kms_key_arn" {
  type = string
}

variable "engine_version" {
  type    = string
  default = "16.6"
}

variable "instance_class" {
  type    = string
  default = "db.r7g.large"
}

variable "allocated_storage_gb" {
  type    = number
  default = 100
}

variable "max_allocated_storage_gb" {
  type    = number
  default = 2000
}

variable "multi_az" {
  type    = bool
  default = true
}

variable "read_replica_count" {
  type    = number
  default = 0
}

variable "backup_retention_days" {
  type    = number
  default = 35
}

variable "deletion_protection" {
  type    = bool
  default = true
}
