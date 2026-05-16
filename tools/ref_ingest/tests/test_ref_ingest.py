"""Round-trip test for the Python reference ingestion.

Mirrors crates/store's `schema_applies_and_roundtrips` and additionally
exercises the OTel->schema mapper + the trace-before-spans FK ordering.
Run from repo root: python -m pytest tools/ref_ingest -q
"""

from __future__ import annotations

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import (
    ResourceSpans,
    ScopeSpans,
    Span,
    Status,
)

from tools.ref_ingest.mapper import ingest_request
from tools.ref_ingest.store import Store


def kv(key: str, value) -> KeyValue:
    av = AnyValue()
    if isinstance(value, bool):
        av.bool_value = value
    elif isinstance(value, int):
        av.int_value = value
    elif isinstance(value, float):
        av.double_value = value
    else:
        av.string_value = str(value)
    return KeyValue(key=key, value=av)


def _request() -> ExportTraceServiceRequest:
    tid = b"\x11" * 16
    root = Span(
        trace_id=tid, span_id=b"\x01" * 8, name="support-bot",
        start_time_unix_nano=1_000_000_000, end_time_unix_nano=4_000_000_000,
        attributes=[kv("stethoscope.kind", "node_execution")],
    )
    llm = Span(
        trace_id=tid, span_id=b"\x02" * 8, parent_span_id=b"\x01" * 8,
        name="llm:claude-opus-4-7",
        start_time_unix_nano=1_100_000_000, end_time_unix_nano=2_900_000_000,
        attributes=[
            kv("gen_ai.system", "anthropic"),
            kv("gen_ai.request.model", "claude-opus-4-7"),
            kv("gen_ai.usage.input_tokens", 824),
            kv("gen_ai.usage.output_tokens", 92),
            kv("stethoscope.cost_usd", 0.0124),
            kv("gen_ai.prompt.0.role", "user"),
            kv("gen_ai.prompt.0.content", "hello"),
            kv("gen_ai.completion.0.content", "hi back"),
        ],
    )
    tool = Span(
        trace_id=tid, span_id=b"\x03" * 8, parent_span_id=b"\x01" * 8,
        name="tool:send_email",
        start_time_unix_nano=3_000_000_000, end_time_unix_nano=3_500_000_000,
        attributes=[
            kv("stethoscope.kind", "tool_call"),
            kv("gen_ai.tool.name", "send_email"),
            kv("stethoscope.tool.arguments", '{"to":"x"}'),
            kv("stethoscope.tool.error", "SMTP timeout"),
        ],
        status=Status(code=2, message="SMTP timeout"),
    )
    return ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                resource=Resource(
                    attributes=[
                        kv("stethoscope.project", "agent_v3"),
                        kv("stethoscope.framework", "langgraph"),
                        kv("stethoscope.framework_version", "0.2.0"),
                    ]
                ),
                scope_spans=[ScopeSpans(spans=[root, llm, tool])],
            )
        ]
    )


def test_ingest_roundtrip():
    store = Store.open_in_memory()
    n = ingest_request(store, _request())
    assert n == 3

    traces = store.list_traces(None)
    assert len(traces) == 1
    t = traces[0]
    assert t.label == "support-bot"
    assert t.status == "failed"  # tool span errored
    assert t.span_count == 3
    assert t.total_tokens_in == 824
    assert t.total_tokens_out == 92
    assert abs((t.total_cost_usd or 0) - 0.0124) < 1e-9
    assert t.agent_framework == "langgraph"
    assert t.is_branch is False

    # project resolved by name
    assert [n for _, n in store.list_projects()] == ["agent_v3"]


def test_idempotent_reingest():
    store = Store.open_in_memory()
    req = _request()
    ingest_request(store, req)
    ingest_request(store, req)  # INSERT OR REPLACE -> still one trace
    traces = store.list_traces(None)
    assert len(traces) == 1
    assert traces[0].span_count == 3
