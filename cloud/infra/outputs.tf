# Everything the operator (or CI) needs after a successful apply.

output "cloudfront_url" {
  description = "Public URL — UI + API. Use for STETHOSCOPE_ENDPOINT and the browser."
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "cloudfront_distribution_id" {
  description = "Pass to `aws cloudfront create-invalidation` after each UI deploy."
  value       = aws_cloudfront_distribution.main.id
}

output "custom_domain_url" {
  description = "Set when var.domain_name is configured."
  value       = local.use_custom_domain ? "https://${var.domain_name}" : null
}

output "alb_dns" {
  description = "Internal ALB DNS — direct access is blocked by the CF header guard."
  value       = aws_lb.api.dns_name
}

output "ecr_repository_url" {
  description = "Push the image here; GH Actions does this automatically."
  value       = aws_ecr_repository.api.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_api" {
  description = "Pass to `aws ecs update-service --force-new-deployment` to roll the API."
  value       = aws_ecs_service.api.name
}

output "ecs_service_worker" {
  value = aws_ecs_service.worker.name
}

output "rds_endpoint" {
  description = "Internal RDS endpoint — only reachable from the Fargate SG."
  value       = aws_db_instance.pg.address
}

output "ui_bucket" {
  description = "S3 bucket for the static UI; CI runs `aws s3 sync` into this."
  value       = aws_s3_bucket.ui.bucket
}

output "payloads_bucket" {
  value = aws_s3_bucket.payloads.bucket
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "cognito_hosted_ui" {
  description = "Cognito-hosted login URL (free, *.amazoncognito.com)."
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com/login?client_id=${aws_cognito_user_pool_client.web.id}&response_type=code&scope=openid+email+profile&redirect_uri=https://${aws_cloudfront_distribution.main.domain_name}/callback"
}

output "sqs_replay_queue_url" {
  value = aws_sqs_queue.replay.url
}

output "alert_topic_arn" {
  description = "Confirm your subscription email after first apply or alarms won't fire."
  value       = aws_sns_topic.alerts.arn
}

output "gh_deploy_role_arn" {
  description = "Paste into the deploy workflow's role-to-assume."
  value       = length(aws_iam_role.gh_deploy) > 0 ? aws_iam_role.gh_deploy[0].arn : null
}

output "admin_token_secret_arn" {
  description = "ARN of the admin-token secret. Fetch with `aws secretsmanager get-secret-value` to call /tenants."
  value       = aws_secretsmanager_secret.admin_token.arn
}
