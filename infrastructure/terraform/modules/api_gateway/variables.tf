variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "cloud_map_service_arn" {
  type = string
}

variable "routes" {
  description = "Routes exposed to partners (everything else stays private to the UI path)."
  type        = list(string)
  default = [
    "POST /api/v1/auth/token",
    "POST /api/v1/surveillance/signals",
    "POST /api/v1/surveillance/cases",
    "GET /api/v1/alerts",
    "GET /api/v1/diseases",
    "GET /api/v1/regions",
  ]
}

variable "rate_limit" {
  type    = number
  default = 50
}

variable "burst_limit" {
  type    = number
  default = 100
}

variable "custom_domain_name" {
  type    = string
  default = ""
}

variable "certificate_arn" {
  type    = string
  default = ""
}

variable "truststore_uri" {
  description = "s3:// URI of the PEM bundle of partner CA certificates for mutual TLS (optional)"
  type        = string
  default     = ""
}

variable "logs_kms_key_arn" {
  type = string
}

variable "log_retention_days" {
  type    = number
  default = 365
}
