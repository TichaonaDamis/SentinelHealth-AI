variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "audit_bucket_name" {
  type = string
}

variable "phi_bucket_arns" {
  description = "Buckets whose object-level access is recorded as CloudTrail data events"
  type        = list(string)
}

variable "logs_kms_key_arn" {
  type = string
}

variable "enable_guardduty" {
  description = "Disable if GuardDuty is managed centrally by an AWS Organizations delegated admin"
  type        = bool
  default     = true
}

variable "enable_security_hub" {
  type    = bool
  default = true
}

variable "enable_config" {
  type    = bool
  default = true
}
