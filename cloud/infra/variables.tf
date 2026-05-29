# All knobs the operator can twist without editing .tf files. Production-shape
# defaults are conservative: scale-to-zero by default so a forgotten apply
# doesn't drain the AWS Free Plan credit. Bring services up with
# `terraform apply -var api_desired_count=1`.

variable "region" {
  description = "Primary AWS region (everything except CloudFront ACM lives here)"
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Name prefix for all resources"
  type        = string
  default     = "stethoscope"
}

variable "environment" {
  description = "dev | staging | prod — gates safety toggles (skip_final_snapshot, deletion_protection)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod"
  }
}

variable "image_tag" {
  description = "Cloud API image tag in ECR (the GH Actions deploy job pushes by commit SHA; first apply uses 'bootstrap')"
  type        = string
  default     = "bootstrap"
}

variable "db_username" {
  description = "RDS master username"
  type        = string
  default     = "stethoscope"
}

variable "db_password" {
  description = "RDS master password — pass via -var or terraform.tfvars (never commit)"
  type        = string
  sensitive   = true
}

variable "db_instance_class" {
  description = "RDS instance class. db.t3.micro is the Free Tier eligible default."
  type        = string
  default     = "db.t3.micro"
}

variable "db_multi_az" {
  description = "Multi-AZ RDS (doubles cost; on for prod-only by default)"
  type        = bool
  default     = false
}

variable "api_desired_count" {
  description = "Fargate API task count. 0 = scaled to zero (saves Fargate hours but ALB still costs)."
  type        = number
  default     = 0
}

variable "worker_desired_count" {
  description = "Fargate worker (replay queue poller) task count. Default 0 — see RUNBOOK §replay for why."
  type        = number
  default     = 0
}

variable "api_max_count" {
  description = "Autoscaling upper bound for the API service"
  type        = number
  default     = 4
}

variable "api_cpu" {
  description = "Fargate CPU units for the API task (256 = .25 vCPU)"
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Fargate memory MB for the API task"
  type        = number
  default     = 1024
}

variable "alert_email" {
  description = "Email subscribed to budget + CloudWatch alarms (confirm via AWS-sent email)"
  type        = string
}

variable "budget_forecast_usd" {
  description = "Monthly forecasted-spend budget that triggers an email warning"
  type        = number
  default     = 5
}

variable "budget_hard_cap_usd" {
  description = "Actual-spend hard cap that triggers Budget Actions to stop the API service"
  type        = number
  default     = 20
}

variable "domain_name" {
  description = "Optional custom domain (e.g. stethoscope.example.com). Empty = use CloudFront's free *.cloudfront.net."
  type        = string
  default     = ""
}

variable "hosted_zone_id" {
  description = "Route 53 hosted zone ID for var.domain_name (only used if domain_name set)"
  type        = string
  default     = ""
}

variable "gh_repo" {
  description = "GitHub repo (owner/name) allowed to assume the deploy role via OIDC"
  type        = string
  default     = ""
}
