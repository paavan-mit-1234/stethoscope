# Three roles:
#   1. Task execution role — Fargate uses this to pull images + fetch secrets
#      (before the container starts).
#   2. Task role — the container itself uses this at runtime (S3, SQS).
#   3. GH Actions OIDC role — assumed by the CI workflow to push images and
#      roll the service. No long-lived AWS keys in GitHub.

# ---- task execution role --------------------------------------------------

data "aws_iam_policy_document" "task_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_exec" {
  name               = "${local.name_prefix}-task-exec"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
}

resource "aws_iam_role_policy_attachment" "task_exec_managed" {
  role       = aws_iam_role.task_exec.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_exec_secrets" {
  role = aws_iam_role.task_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.db_url.arn,
        aws_secretsmanager_secret.jwt.arn,
        aws_secretsmanager_secret.admin_token.arn,
      ]
    }]
  })
}

# ---- task role (runtime) --------------------------------------------------

resource "aws_iam_role" "task" {
  name               = "${local.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
}

resource "aws_iam_role_policy" "task_runtime" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.payloads.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = [aws_sqs_queue.replay.arn]
      },
    ]
  })
}

# ---- GitHub Actions OIDC role --------------------------------------------
# We always create the OIDC provider when var.gh_repo is set. If the
# account already has the provider from a previous project, the first
# apply will fail with "EntityAlreadyExists" — fix once with:
#
#   terraform import \
#     'aws_iam_openid_connect_provider.github[0]' \
#     arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com
#
# Documented in RUNBOOK §oidc-import.

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.gh_repo == "" ? 0 : 1
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # GitHub's intermediate cert thumbprint — kept current in the AWS docs.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "gh_assume" {
  count = var.gh_repo == "" ? 0 : 1
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.gh_repo}:*"]
    }
  }
}

resource "aws_iam_role" "gh_deploy" {
  count              = var.gh_repo == "" ? 0 : 1
  name               = "${local.name_prefix}-gh-deploy"
  assume_role_policy = data.aws_iam_policy_document.gh_assume[0].json
}

resource "aws_iam_role_policy" "gh_deploy" {
  count = var.gh_repo == "" ? 0 : 1
  role  = aws_iam_role.gh_deploy[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
          "ecr:DescribeRepositories",
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:UpdateService", "ecs:DescribeServices", "ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.task_exec.arn, aws_iam_role.task.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.ui.arn, "${aws_s3_bucket.ui.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation"]
        Resource = aws_cloudfront_distribution.main.arn
      },
    ]
  })
}
