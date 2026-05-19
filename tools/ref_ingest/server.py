"""OTLP/gRPC receiver — Python reference mirroring crates/ingestion.

Implements the OpenTelemetry TraceService so any OTLP exporter (including
stethoscope-py) can ship spans to localhost:4317.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent import futures

import grpc
from opentelemetry.proto.collector.trace.v1 import (
    trace_service_pb2,
    trace_service_pb2_grpc,
)

from .mapper import ingest_request
from .store import Store

_log = logging.getLogger("stethoscope.ingest")

DEFAULT_OTLP_ADDR = "127.0.0.1:4317"


def default_db_path(project: str = "default") -> str:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or "."
    return os.path.join(home, ".stethoscope", "projects", project, "traces.db")


class _TraceService(trace_service_pb2_grpc.TraceServiceServicer):
    def __init__(self, store: Store, lock: threading.Lock):
        self._store = store
        self._lock = lock  # shared with the read API; duckdb is 1-threaded

    def Export(self, request, context):
        try:
            with self._lock:
                n = ingest_request(self._store, request)
            _log.info("ingested OTLP batch: %d span(s)", n)
        except Exception as exc:  # never crash the receiver
            _log.exception("ingest failed: %s", exc)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
        return trace_service_pb2.ExportTraceServiceResponse()


def serve(addr: str = DEFAULT_OTLP_ADDR, db_path: str | None = None) -> None:
    db_path = db_path or default_db_path()
    store = Store.open(db_path)
    lock = threading.Lock()  # serializes the single duckdb connection

    # Read API (Phase 3) shares this store+lock with the gRPC receiver.
    from .api import serve_api

    api = serve_api(store, lock)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    trace_service_pb2_grpc.add_TraceServiceServicer_to_server(
        _TraceService(store, lock), server
    )
    server.add_insecure_port(addr)
    server.start()
    _log.info("Stethoscope ingestion listening on %s (OTLP/gRPC) -> %s",
              addr, db_path)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        _log.info("shutdown signal received")
        server.stop(grace=2)
        api.shutdown()
