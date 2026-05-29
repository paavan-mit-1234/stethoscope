# Cognito user pool — the prod auth backend (auth_cognito.py reads tokens
# via JWKS). Cognito's free tier covers 50k MAU forever, so this never
# costs money at our scale.
#
# Per-tenant association: the `custom:tenant_id` attribute is set at signup
# by a pre-token-generation trigger (deferred — Cloud Phase 3) or
# administratively. For Phase 1 the API issues local HS256 tokens by default
# and we only flip to Cognito by setting `STETHOSCOPE_AUTH=cognito` on the
# task definition (done in ecs_api.tf).

resource "aws_cognito_user_pool" "main" {
  name = "${local.name_prefix}-users"

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "tenant_id"
    attribute_data_type = "String"
    mutable             = true
    required            = false
    string_attribute_constraints {
      min_length = 1
      max_length = 64
    }
  }

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  deletion_protection = local.is_prod ? "ACTIVE" : "INACTIVE"
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name_prefix}-web"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret        = false # SPA/PKCE; no client secret
  refresh_token_validity = 30
  access_token_validity  = 1
  id_token_validity      = 1
  token_validity_units {
    refresh_token = "days"
    access_token  = "hours"
    id_token      = "hours"
  }

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  prevent_user_existence_errors = "ENABLED"

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = local.use_custom_domain ? [
    "https://${var.domain_name}/callback",
    ] : [
    "https://${aws_cloudfront_distribution.main.domain_name}/callback",
  ]
  logout_urls = local.use_custom_domain ? [
    "https://${var.domain_name}/",
    ] : [
    "https://${aws_cloudfront_distribution.main.domain_name}/",
  ]
}

# Hosted UI domain — prefix mode is free. Custom Cognito domains require an
# ACM cert; skip for the no-domain demo path.
resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project}-${local.environment_slug}-${substr(local.account_id, 0, 6)}"
  user_pool_id = aws_cognito_user_pool.main.id
}
