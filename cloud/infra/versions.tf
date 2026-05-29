# Terraform + provider versions. The us-east-1 alias is mandatory for
# CloudFront-attached ACM certificates (CloudFront only honours certs in
# us-east-1) — we declare it unconditionally and use it only when
# var.domain_name is set.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = local.common_tags
  }
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = local.common_tags
  }
}

data "aws_caller_identity" "me" {}
data "aws_partition" "current" {}
