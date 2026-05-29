# Postgres in private subnets. Single-AZ + t3.micro by default to stay in
# Free Tier; flip var.db_multi_az + bump var.db_instance_class for prod.
#
# Deletion safety: skip_final_snapshot is dynamic — true for non-prod so
# `terraform destroy` works without manual snapshot, false in prod so an
# accidental destroy creates a recovery snapshot. deletion_protection is
# on for prod.

resource "aws_db_subnet_group" "pg" {
  name       = "${local.name_prefix}-pg"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${local.name_prefix}-pg" }
}

resource "aws_db_parameter_group" "pg16" {
  name   = "${local.name_prefix}-pg16"
  family = "postgres16"

  parameter {
    name  = "log_min_duration_statement"
    value = "1000" # log queries slower than 1s
  }
}

resource "aws_db_instance" "pg" {
  identifier            = "${local.name_prefix}-pg"
  engine                = "postgres"
  engine_version        = "16"
  instance_class        = var.db_instance_class
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_encrypted     = true

  db_name  = "stethoscope"
  username = var.db_username
  password = var.db_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.pg.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  multi_az                     = var.db_multi_az
  backup_retention_period      = local.is_prod ? 7 : 1
  backup_window                = "03:00-04:00" # UTC; ~08:30-09:30 IST
  maintenance_window           = "Sun:04:30-Sun:05:30"
  auto_minor_version_upgrade   = true
  performance_insights_enabled = false

  parameter_group_name      = aws_db_parameter_group.pg16.name
  deletion_protection       = local.is_prod
  skip_final_snapshot       = !local.is_prod
  final_snapshot_identifier = local.is_prod ? "${local.name_prefix}-pg-final-${formatdate("YYYYMMDDhhmmss", timestamp())}" : null
  apply_immediately         = !local.is_prod

  # Avoid replacement when the snapshot identifier changes from timestamp().
  lifecycle {
    ignore_changes = [final_snapshot_identifier]
  }
}
