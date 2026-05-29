# ECS Fargate cluster + API service + ALB.
#
# Scale-to-zero by default (var.api_desired_count = 0) so a forgotten apply
# doesn't drain Free Plan credit — bring up with -var api_desired_count=1.
# Autoscaling tracks CPU at 60% between min=desired and max=var.api_max_count.

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = local.is_prod ? "enabled" : "disabled"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name_prefix}-api"
  retention_in_days = local.is_prod ? 30 : 7
}

# ---- ALB ------------------------------------------------------------------

resource "aws_lb" "api" {
  name               = "${local.name_prefix}-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  drop_invalid_header_fields = true
  idle_timeout               = 60
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name_prefix}-api-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30
}

# Default action: reject. Only requests carrying the CloudFront origin
# secret header are forwarded — prevents direct ALB access bypassing CF.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "direct access denied; use CloudFront"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "cf_only" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    http_header {
      http_header_name = "X-CF-Origin-Secret"
      values           = [random_password.cf_origin_secret.result]
    }
  }
}

# ---- task definition ------------------------------------------------------

locals {
  api_container = {
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential = true
    portMappings = [{
      containerPort = 8080
      protocol      = "tcp"
    }]
    environment = [
      { name = "STETHOSCOPE_ENV", value = var.environment },
      { name = "STETHOSCOPE_STORE", value = "postgres" },
      { name = "STETHOSCOPE_S3_BUCKET", value = aws_s3_bucket.payloads.bucket },
      { name = "STETHOSCOPE_S3_PREFIX", value = "payloads/" },
      { name = "STETHOSCOPE_S3_THRESHOLD", value = "16384" },
      { name = "STETHOSCOPE_SQS_QUEUE_URL", value = aws_sqs_queue.replay.url },
      { name = "STETHOSCOPE_CORS_ORIGINS", value = local.cors_origins },
      { name = "STETHOSCOPE_AUTH", value = "cognito" },
      { name = "COGNITO_REGION", value = var.region },
      { name = "COGNITO_USER_POOL_ID", value = aws_cognito_user_pool.main.id },
      { name = "COGNITO_CLIENT_ID", value = aws_cognito_user_pool_client.web.id },
      { name = "AWS_REGION", value = var.region },
    ]
    secrets = [
      { name = "STETHOSCOPE_DATABASE_URL", valueFrom = aws_secretsmanager_secret.db_url.arn },
      { name = "STETHOSCOPE_JWT_SECRET", valueFrom = aws_secretsmanager_secret.jwt.arn },
      { name = "STETHOSCOPE_ADMIN_TOKEN", valueFrom = aws_secretsmanager_secret.admin_token.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "api"
      }
    }
    healthCheck = {
      command  = ["CMD-SHELL", "python -c \"import urllib.request as u; u.urlopen('http://127.0.0.1:8080/health',timeout=2)\" || exit 1"]
      interval = 30
      timeout  = 5
      retries  = 3
    }
  }
  cors_origins = local.use_custom_domain ? "https://${var.domain_name}" : "https://${aws_cloudfront_distribution.main.domain_name}"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.task_exec.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = jsonencode([local.api_container])
}

# ---- service --------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name            = "${local.name_prefix}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.svc.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8080
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  # The GH Actions deploy job updates the task definition image; ignore
  # changes here so re-running terraform after a deploy doesn't roll back.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener_rule.cf_only]
}

# ---- autoscaling (only when desired_count > 0) ---------------------------

resource "aws_appautoscaling_target" "api" {
  count              = var.api_desired_count > 0 ? 1 : 0
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.api_desired_count
  max_capacity       = var.api_max_count
}

resource "aws_appautoscaling_policy" "api_cpu" {
  count              = var.api_desired_count > 0 ? 1 : 0
  name               = "${local.name_prefix}-api-cpu60"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api[0].service_namespace
  resource_id        = aws_appautoscaling_target.api[0].resource_id
  scalable_dimension = aws_appautoscaling_target.api[0].scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = 60.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}
