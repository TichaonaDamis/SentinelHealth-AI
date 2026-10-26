variable "name" {
  type = string
}

variable "region" {
  type = string
}

variable "cidr_block" {
  type    = string
  default = "10.40.0.0/16"
}

variable "az_count" {
  type    = number
  default = 3
}

variable "single_nat_gateway" {
  description = "One NAT gateway for cost savings (dev); one per AZ for HA (prod)."
  type        = bool
  default     = false
}

variable "logs_kms_key_arn" {
  type = string
}

variable "log_retention_days" {
  type    = number
  default = 365
}
