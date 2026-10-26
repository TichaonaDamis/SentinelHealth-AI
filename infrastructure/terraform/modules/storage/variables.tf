variable "name" {
  type = string
}

variable "account_id" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "raw_retention_days" {
  type    = number
  default = 400
}

variable "audit_retention_days" {
  description = "HIPAA 45 CFR 164.316(b)(2): retain documentation 6 years."
  type        = number
  default     = 2190
}

variable "force_destroy" {
  type    = bool
  default = false
}
