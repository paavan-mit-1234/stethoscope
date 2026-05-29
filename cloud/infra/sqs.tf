# Replay job queue + dead-letter queue. The API's POST /branch enqueues here
# when STETHOSCOPE_SQS_QUEUE_URL is set; the worker (ecs_worker.tf) polls.
#
# Cloud Phase 1 honest disclosure: the worker is a stub (see
# cloud/api/worker.py + RUNBOOK §replay). The infrastructure is here so the
# *shape* is right for a portfolio review; messages just get logged and
# acked until customer-side runner support lands.

resource "aws_sqs_queue" "replay_dlq" {
  name                      = "${local.name_prefix}-replay-dlq"
  message_retention_seconds = 1209600 # 14 days max
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "replay" {
  name                       = "${local.name_prefix}-replay"
  visibility_timeout_seconds = 120
  message_retention_seconds  = 86400 # 1 day
  receive_wait_time_seconds  = 20    # long-poll
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.replay_dlq.arn
    maxReceiveCount     = 5
  })
}
