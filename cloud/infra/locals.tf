# Naming + tagging conventions. Every taggable resource picks these up via
# the provider default_tags block in versions.tf, so the per-resource tag = {}
# stanza is only needed when a resource needs *extra* tags.

locals {
  name_prefix = "${var.project}-${var.environment}"

  # AWS Application Auto Scaling rejects empty tag values, so the Repo
  # tag is added only when var.gh_repo is non-empty.
  common_tags = merge(
    {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    },
    var.gh_repo == "" ? {} : { Repo = var.gh_repo }
  )

  is_prod            = var.environment == "prod"
  use_custom_domain  = var.domain_name != ""
  account_id         = data.aws_caller_identity.me.account_id
  partition          = data.aws_partition.current.partition
  cloudfront_aliases = var.domain_name != "" ? [var.domain_name] : []
  environment_slug   = replace(var.environment, "_", "-")
}
