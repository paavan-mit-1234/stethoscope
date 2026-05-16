"""OpenTelemetry wiring: resource attributes + OTLP/gRPC exporter."""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .config import StethoscopeConfig

_log = logging.getLogger("stethoscope")
_PROVIDER: TracerProvider | None = None

TRACER_NAME = "stethoscope-py"


def init_tracer(config: StethoscopeConfig) -> trace.Tracer:
    """Idempotently install a TracerProvider exporting to the Stethoscope
    ingestion endpoint, and return a tracer."""
    global _PROVIDER

    if _PROVIDER is None:
        resource = Resource.create(
            {
                "service.name": config.project,
                "stethoscope.project": config.project,
                "stethoscope.framework": config.framework,
                **(
                    {"stethoscope.framework_version": config.framework_version}
                    if config.framework_version
                    else {}
                ),
            }
        )
        provider = TracerProvider(resource=resource)
        endpoint = config.endpoint
        if "://" not in endpoint:
            endpoint = f"http://{endpoint}"
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True, timeout=5)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _PROVIDER = provider
        _log.info("stethoscope: exporting traces to %s", endpoint)

    return trace.get_tracer(TRACER_NAME)


def shutdown() -> None:
    """Flush and tear down the exporter (call before process exit)."""
    global _PROVIDER
    if _PROVIDER is not None:
        try:
            _PROVIDER.shutdown()
        finally:
            _PROVIDER = None
