# Three secrets — all consumed by the ECS task definition as `secrets:`
# entries, so the container sees them as env vars but they're never in the
# task definition JSON.
#
# 1. db_url        — Postgres connection string for the runtime
# 2. jwt           — HS256 signing secret for app-issued JWTs
# 3. admin_token   — bearer token gating /tenants (admin-only mint route)

resource "random_password" "jwt" {
  length  = 48
  special = false
}

resource "random_password" "admin_token" {
  length  = 32
  special = false
}

resource "random_password" "cf_origin_secret" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "db_url" {
  name = "${local.name_prefix}/database-url"
  # Allow re-create within 7 days if accidentally destroyed in dev.
  recovery_window_in_days = local.is_prod ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id     = aws_secretsmanager_secret.db_url.id
  secret_string = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.pg.address}:5432/stethoscope"
}

resource "aws_secretsmanager_secret" "jwt" {
  name                    = "${local.name_prefix}/jwt-secret"
  recovery_window_in_days = local.is_prod ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "jwt" {
  secret_id     = aws_secretsmanager_secret.jwt.id
  secret_string = random_password.jwt.result
}

resource "aws_secretsmanager_secret" "admin_token" {
  name                    = "${local.name_prefix}/admin-token"
  recovery_window_in_days = local.is_prod ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "admin_token" {
  secret_id     = aws_secretsmanager_secret.admin_token.id
  secret_string = random_password.admin_token.result
}
