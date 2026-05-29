# CloudFront in front of two origins:
#   /api/* + /v1/* + /auth/* + /share/* + /tenants + /traces + ... → ALB
#   everything else                                                → S3 (UI)
#
# Without a custom domain, CloudFront's default cert covers
# *.cloudfront.net for free — production-shaped TLS at $0. When a domain is
# brought, we add aws_acm_certificate (us-east-1, DNS validation) and an
# alias here.

# OAC: lets CloudFront read from the private S3 bucket without making it
# public. The bucket policy in s3.tf only trusts requests carrying this OAC.
resource "aws_cloudfront_origin_access_control" "ui" {
  name                              = "${local.name_prefix}-ui-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Optional ACM cert (us-east-1) when a custom domain is configured.
resource "aws_acm_certificate" "cf" {
  count             = local.use_custom_domain ? 1 : 0
  provider          = aws.us_east_1
  domain_name       = var.domain_name
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

# DNS validation records — only created if a hosted zone is provided.
resource "aws_route53_record" "cf_cert_validation" {
  for_each = local.use_custom_domain && var.hosted_zone_id != "" ? {
    for dvo in aws_acm_certificate.cf[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  zone_id = var.hosted_zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60
}

resource "aws_acm_certificate_validation" "cf" {
  count                   = local.use_custom_domain && var.hosted_zone_id != "" ? 1 : 0
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.cf[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cf_cert_validation : r.fqdn]
}

# ---- distribution ---------------------------------------------------------

resource "aws_cloudfront_distribution" "main" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${local.name_prefix} API and UI"
  price_class     = "PriceClass_100" # NA + EU edges; cheapest tier
  http_version    = "http2"
  aliases         = local.cloudfront_aliases

  # ---- origins ----
  origin {
    origin_id   = "alb"
    domain_name = aws_lb.api.dns_name
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only" # ALB is HTTP; CF handles TLS
      origin_ssl_protocols   = ["TLSv1.2"]
    }
    custom_header {
      name  = "X-CF-Origin-Secret"
      value = random_password.cf_origin_secret.result
    }
  }

  origin {
    origin_id                = "ui-s3"
    domain_name              = aws_s3_bucket.ui.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.ui.id
  }

  # ---- default (UI) ----
  default_cache_behavior {
    target_origin_id       = "ui-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized
  }

  # SPA fallback: serve index.html for unknown paths so React Router works.
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  # ---- API routes (forward to ALB) ----
  dynamic "ordered_cache_behavior" {
    for_each = toset([
      "/v1/*", "/auth/*", "/traces/*", "/spans/*", "/projects",
      "/projects/*", "/breakpoints", "/breakpoints/*", "/tenants",
      "/branch", "/share/*", "/health", "/health/*",
    ])
    content {
      path_pattern           = ordered_cache_behavior.key
      target_origin_id       = "alb"
      viewer_protocol_policy = "redirect-to-https"
      allowed_methods        = ["GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH"]
      cached_methods         = ["GET", "HEAD"]
      compress               = true

      cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
      origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewer (forwards headers + body)
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = !local.use_custom_domain
    acm_certificate_arn            = local.use_custom_domain ? aws_acm_certificate.cf[0].arn : null
    ssl_support_method             = local.use_custom_domain ? "sni-only" : null
    minimum_protocol_version       = local.use_custom_domain ? "TLSv1.2_2021" : "TLSv1"
  }

  # When a domain is set, wait for cert validation before deploying.
  depends_on = [aws_acm_certificate_validation.cf]
}
