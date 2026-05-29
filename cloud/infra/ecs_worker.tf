# Replay worker — same image as the API, different CMD (run cloud.api.worker
# instead of uvicorn). Scale-to-zero default.

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.name_prefix}-worker"
  retention_in_days = local.is_prod ? 30 : 7
}

locals {
  worker_container = {
    name      = "worker"
    image     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential = true
    command   = ["python", "-m", "cloud.api.worker"]
    environment = [
      { name = "STETHOSCOPE_ENV", value = var.environment },
      { name = "STETHOSCOPE_STORE", value = "postgres" },
      { name = "STETHOSCOPE_SQS_QUEUE_URL", value = aws_sqs_queue.replay.url },
      { name = "STETHOSCOPE_S3_BUCKET", value = aws_s3_bucket.payloads.bucket },
      { name = "STETHOSCOPE_S3_PREFIX", value = "payloads/" },
      { name = "AWS_REGION", value = var.region },
      { name = "LOG_LEVEL", value = "INFO" },
    ]
    secrets = [
      { name = "STETHOSCOPE_DATABASE_URL", valueFrom = aws_secretsmanager_secret.db_url.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task_exec.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = jsonencode([local.worker_container])
}

resource "aws_ecs_service" "worker" {
  name            = "${local.name_prefix}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.svc.id]
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
}
