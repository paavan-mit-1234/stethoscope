"""SQS-backed replay worker (Cloud Phase 3 placeholder).

What this *should* do once Phase 3 is implemented: poll the replay queue,
deserialize a manifest, run the customer's agent against captured LLM/tool
fixtures, ship resulting traces back via OTLP/HTTP to the same cloud API.

What it actually does today: log the request and return a 501-shaped error,
because **the cloud can't replay a customer's agent without the agent's
source code**. The local desktop reference (``tools/ref_replay``) runs the
agent in a subprocess from a path on the same machine — that contract
doesn't translate to a multi-tenant cloud worker.

The honest paths forward (deferred, documented in cloud/RUNBOOK.md):

1. **Customer-side runner** — ship a CLI that subscribes to the replay
   queue and runs locally. Cloud schedules, customer executes, traces
   ship back. Best fit for the desktop-first PRD framing.
2. **Sandboxed container per project** — customer uploads a Dockerfile
   describing their agent; cloud runs it on Fargate per replay request.
   Expensive, requires per-tenant images and secrets management.
3. **Cached-only replay** — refuse "structural" replays; only honor
   identical re-runs of cached LLM responses. Works for one PRD use case
   (deterministic diff) but breaks the mutation feature.

The Terraform still provisions the SQS queue + worker task definition with
``desired_count = 0`` so the *shape* is right for a portfolio review,
without paying for an idle worker.

Run locally for development::

    STETHOSCOPE_DATABASE_URL=postgresql://...  \
    STETHOSCOPE_SQS_QUEUE_URL=https://sqs.../q  \
    python -m cloud.api.worker
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time

log = logging.getLogger("stethoscope.worker")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

QUEUE_URL = os.environ.get("STETHOSCOPE_SQS_QUEUE_URL", "")
POLL_WAIT_SECONDS = int(os.environ.get("STETHOSCOPE_SQS_WAIT", "20"))
VISIBILITY_TIMEOUT = int(os.environ.get("STETHOSCOPE_SQS_VISIBILITY", "120"))

_keep_running = True


def _stop(*_):
    global _keep_running
    log.info("received shutdown signal — draining current poll cycle")
    _keep_running = False


def process_message(msg: dict) -> bool:
    """Handle one replay request. Return True on success (so SQS deletes it),
    False on permanent failure (still delete so it doesn't loop forever), or
    raise to leave it in the queue for retry.

    Phase 1 behaviour: log + acknowledge. The API returns a 501 to the
    caller, so the queue stays empty in practice.
    """
    try:
        body = json.loads(msg.get("Body", "{}"))
    except json.JSONDecodeError:
        log.error("malformed body — dropping: %r", msg.get("Body"))
        return False

    log.warning(
        "replay request received for tenant=%s trace=%s — cloud replay "
        "not implemented; use the desktop app or a customer-side runner",
        body.get("tenant_id"),
        body.get("source_trace_id"),
    )
    # Future: enqueue a customer-runner notification, mark the branch as
    # 'awaiting_customer_runner' in the DB, etc.
    return True


def main() -> int:
    if not QUEUE_URL:
        log.error("STETHOSCOPE_SQS_QUEUE_URL is required")
        return 2

    import boto3  # pyright: ignore[reportMissingImports]

    sqs = boto3.client("sqs")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started; polling %s", QUEUE_URL)

    while _keep_running:
        resp = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=POLL_WAIT_SECONDS,
            VisibilityTimeout=VISIBILITY_TIMEOUT,
        )
        for msg in resp.get("Messages", []):
            try:
                handled = process_message(msg)
            except Exception:
                log.exception("processing failed — message will be retried")
                continue
            if handled:
                sqs.delete_message(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
        if not resp.get("Messages"):
            # Heartbeat so the ECS task log isn't silent.
            time.sleep(1)

    log.info("worker exiting cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
