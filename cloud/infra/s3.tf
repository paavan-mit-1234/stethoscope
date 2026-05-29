# Two buckets: payloads (large trace content offload) and UI (static SPA).
# Both block public access; the UI bucket is reached only via CloudFront
# using an Origin Access Control (OAC).
#
# Naming: bucket names are globally unique — we suffix the account ID so
# two people deploying this code don't collide.

# ---- payloads -------------------------------------------------------------

resource "aws_s3_bucket" "payloads" {
  bucket        = "${var.project}-payloads-${local.environment_slug}-${local.account_id}"
  force_destroy = !local.is_prod
}

resource "aws_s3_bucket_public_access_block" "payloads" {
  bucket                  = aws_s3_bucket.payloads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "payloads" {
  bucket = aws_s3_bucket.payloads.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "payloads" {
  bucket = aws_s3_bucket.payloads.id

  rule {
    id     = "glacier-90d"
    status = "Enabled"
    filter {}
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
    expiration {
      days = 365 # tunable; conservative starting point
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# ---- UI static site -------------------------------------------------------

resource "aws_s3_bucket" "ui" {
  bucket        = "${var.project}-ui-${local.environment_slug}-${local.account_id}"
  force_destroy = !local.is_prod
}

resource "aws_s3_bucket_public_access_block" "ui" {
  bucket                  = aws_s3_bucket.ui.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ui" {
  bucket = aws_s3_bucket.ui.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Bucket policy granting read access to CloudFront's OAC only.
data "aws_iam_policy_document" "ui_bucket" {
  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.ui.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.main.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "ui" {
  bucket = aws_s3_bucket.ui.id
  policy = data.aws_iam_policy_document.ui_bucket.json
}
