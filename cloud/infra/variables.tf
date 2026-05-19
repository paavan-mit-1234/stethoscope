variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Name prefix for all resources"
  type        = string
  default     = "stethoscope"
}

variable "image_tag" {
  description = "Cloud API image tag in ECR (pushed by the runbook)"
  type        = string
  default     = "latest"
}

variable "db_username" {
  type    = string
  default = "stethoscope"
}

variable "db_password" {
  description = "RDS master password (store in tfvars / CI secret, never commit)"
  type        = string
  sensitive   = true
}

variable "desired_count" {
  description = "Fargate task count"
  type        = number
  default     = 1
}
