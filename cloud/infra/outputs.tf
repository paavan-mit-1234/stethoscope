output "api_url" {
  description = "Public API base URL (point STETHOSCOPE_ENDPOINT at <this>/v1/traces)"
  value       = "http://${aws_lb.api.dns_name}"
}

output "ecr_repository_url" {
  description = "Push the cloud API image here (see runbook)"
  value       = aws_ecr_repository.api.repository_url
}

output "payloads_bucket" {
  value = aws_s3_bucket.payloads.bucket
}

output "rds_address" {
  value = aws_db_instance.pg.address
}
