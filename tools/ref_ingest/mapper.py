"""OTel GenAI conventions -> Stethoscope schema (PRD section 7.4).

Logic mirrors crates/ingestion/src/{otel,mapper}.rs exactly: same attribute
keys, same kind inference, same per-trace aggregation.

Slice limitation (identical to the Rust path): large message/tool payloads
are stored inline, not offloaded to Parquet yet.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

from . import bp
from .ids import ulid
from .schema import SPAN_KIND, TRACE_STATUS
from .store import Store


# ---- attribute helpers (mirror otel.rs) ------------------------------------

def _any_to_py(v):
    kind = v.WhichOneof("value")
    if kind == "string_value":
        return v.string_value
    if kind == "bool_value":
        return v.bool_value
    if kind == "int_value":
        return v.int_value
    if kind == "double_value":
        return v.double_value
    if kind == "bytes_value":
        return v.bytes_value.hex()
    if kind == "array_value":
        return [_any_to_py(x) for x in v.array_value.values]
    if kind == "kvlist_value":
        return _attrs_map(v.kvlist_value.values)
    return None


def _attrs_map(attrs) -> dict:
    return {kv.key: _any_to_py(kv.value) for kv in attrs}


def _find(attrs, key):
    for kv in attrs:
        if kv.key == key:
            return kv.value
    return None


def _get_str(attrs, key):
    v = _find(attrs, key)
    if v is None:
        return None
    return v.string_value if v.WhichOneof("value") == "string_value" else None


def _get_i64(attrs, key):
    v = _find(attrs, key)
    if v is None:
        return None
    k = v.WhichOneof("value")
    if k == "int_value":
        return v.int_value
    if k == "string_value":
        try:
            return int(v.string_value)
        except ValueError:
            return None
    return None


def _get_f64(attrs, key):
    v = _find(attrs, key)
    if v is None:
        return None
    k = v.WhichOneof("value")
    if k == "double_value":
        return v.double_value
    if k == "int_value":
        return float(v.int_value)
    if k == "string_value":
        try:
            return float(v.string_value)
        except ValueError:
            return None
    return None


def _get_bool(attrs, key):
    v = _find(attrs, key)
    if v is None:
        return None
    return v.bool_value if v.WhichOneof("value") == "bool_value" else None


def _ts(nanos: int):
    if not nanos:
        return None
    return datetime.fromtimestamp(nanos / 1e9, tz=timezone.utc).replace(
        tzinfo=None
    )


# ---- mapping (mirror mapper.rs) --------------------------------------------

def _infer_kind(name: str, attrs) -> str:
    k = _get_str(attrs, "stethoscope.kind")
    if k:
        return k
    if _get_str(attrs, "gen_ai.request.model"):
        return SPAN_KIND["LLM_CALL"]
    if _get_str(attrs, "gen_ai.tool.name") or name.startswith("tool:"):
        return SPAN_KIND["TOOL_CALL"]
    return SPAN_KIND["NODE_EXECUTION"]


def _status(span):
    if span.HasField("status") and span.status.code == 2:  # STATUS_CODE_ERROR
        msg = span.status.message
        return "error", (msg or None)
    return "ok", None


def _map_span(trace_id: str, sp) -> dict:
    a = sp.attributes
    st, en = sp.start_time_unix_nano, sp.end_time_unix_nano
    duration_ms = (en - st) // 1_000_000 if (st and en and en >= st) else None
    status, err = _status(sp)
    return {
        "id": sp.span_id.hex(),
        "trace_id": trace_id,
        "parent_span_id": sp.parent_span_id.hex() or None,
        "kind": _infer_kind(sp.name, a),
        "name": sp.name,
        "started_at": _ts(st),
        "ended_at": _ts(en),
        "duration_ms": duration_ms,
        "status": status,
        "error_message": err,
        "cost_usd": _get_f64(a, "stethoscope.cost_usd"),
        "tokens_in": _get_i64(a, "gen_ai.usage.input_tokens"),
        "tokens_out": _get_i64(a, "gen_ai.usage.output_tokens"),
        "tokens_cached": _get_i64(a, "gen_ai.usage.cached_tokens"),
        "model": _get_str(a, "gen_ai.request.model"),
        "provider": _get_str(a, "gen_ai.system"),
        "temperature": _get_f64(a, "gen_ai.request.temperature"),
        "payload_ref": None,
        "prompt_hash": _get_str(a, "stethoscope.prompt_hash"),
        "cacheable": _get_bool(a, "stethoscope.cacheable"),
        "redacted": _get_bool(a, "stethoscope.redacted") or False,
        "attributes_json": json.dumps(_attrs_map(a)),
    }


def _extract_messages(span_id: str, a) -> list[dict]:
    out: list[dict] = []
    seq = 0
    for prefix, default_role in (
        ("gen_ai.prompt", "user"),
        ("gen_ai.completion", "assistant"),
    ):
        i = 0
        while True:
            content = _get_str(a, f"{prefix}.{i}.content")
            if content is None:
                break
            out.append(
                {
                    "id": ulid(),
                    "span_id": span_id,
                    "seq": seq,
                    "role": _get_str(a, f"{prefix}.{i}.role") or default_role,
                    "content_inline": content,
                    "tool_call_id": _get_str(a, f"{prefix}.{i}.tool_call_id"),
                }
            )
            seq += 1
            i += 1
    return out


def _extract_tool_call(span_id: str, a) -> dict | None:
    name = _get_str(a, "gen_ai.tool.name") or _get_str(a, "stethoscope.tool_name")
    if not name:
        return None
    return {
        "span_id": span_id,
        "tool_name": name,
        "arguments_inline": _get_str(a, "stethoscope.tool.arguments"),
        "result_inline": _get_str(a, "stethoscope.tool.result"),
        "error": _get_str(a, "stethoscope.tool.error"),
    }


def _bp_ctx(mapped: dict, tool_name: str | None) -> dict:
    return {
        "kind": mapped["kind"],
        "name": mapped["name"],
        "status": mapped["status"],
        "duration_ms": mapped.get("duration_ms"),
        "model": mapped.get("model"),
        "provider": mapped.get("provider"),
        "tokens_in": mapped.get("tokens_in"),
        "tokens_out": mapped.get("tokens_out"),
        "cost_usd": mapped.get("cost_usd"),
        "error_message": mapped.get("error_message"),
        "tool_name": tool_name,
    }


def ingest_request(store: Store, req: ExportTraceServiceRequest) -> int:
    span_count = 0
    # Compile enabled breakpoints once per batch (PRD 9.5 live detection).
    bps: list[tuple[str, object]] = []
    for b in store.enabled_breakpoints():
        try:
            bps.append((b["id"], bp.parse(b["condition_dsl"])))
        except ValueError:
            pass  # invalid predicate: skip, never break ingestion

    for rs in req.resource_spans:
        res_attrs = rs.resource.attributes if rs.HasField("resource") else []
        project_name = (
            _get_str(res_attrs, "stethoscope.project")
            or _get_str(res_attrs, "service.name")
            or "default"
        )
        project_id = store.ensure_project(project_name)
        framework = _get_str(res_attrs, "stethoscope.framework")
        framework_version = _get_str(res_attrs, "stethoscope.framework_version")

        by_trace: dict[str, list] = {}
        for ss in rs.scope_spans:
            for sp in ss.spans:
                by_trace.setdefault(sp.trace_id.hex(), []).append(sp)

        for trace_id, spans in by_trace.items():
            # Map once; aggregate in pass 1, write in pass 2. The trace row
            # must be inserted before its spans (spans.trace_id FK).
            pairs = [(sp, _map_span(trace_id, sp)) for sp in spans]

            min_start, max_end = None, 0
            any_error = False
            cost = tin = tout = 0
            root_name = None
            parent_trace_id = branch_point = None

            for sp, mapped in pairs:
                if sp.start_time_unix_nano:
                    s = sp.start_time_unix_nano
                    min_start = s if min_start is None else min(min_start, s)
                max_end = max(max_end, sp.end_time_unix_nano)
                any_error |= mapped["status"] == "error"
                cost += mapped["cost_usd"] or 0.0
                tin += mapped["tokens_in"] or 0
                tout += mapped["tokens_out"] or 0
                if not sp.parent_span_id:
                    root_name = sp.name
                p = _get_str(sp.attributes, "stethoscope.parent_trace_id")
                if p:
                    parent_trace_id = p
                b = _get_str(sp.attributes, "stethoscope.branch_point_span_id")
                if b:
                    branch_point = b

            store.upsert_trace(
                {
                    "id": trace_id,
                    "project_id": project_id,
                    "parent_trace_id": parent_trace_id,
                    "branch_point_span_id": branch_point,
                    "label": root_name,
                    "status": TRACE_STATUS["FAILED"]
                    if any_error
                    else TRACE_STATUS["COMPLETED"],
                    "started_at": _ts(min_start or 0) or datetime.utcnow(),
                    "ended_at": _ts(max_end),
                    "total_cost_usd": cost if cost > 0 else None,
                    "total_tokens_in": tin if tin > 0 else None,
                    "total_tokens_out": tout if tout > 0 else None,
                    "agent_framework": framework,
                    "framework_version": framework_version,
                }
            )

            for sp, mapped in pairs:
                store.upsert_span(mapped)
                tool_name = None
                for m in _extract_messages(mapped["id"], sp.attributes):
                    store.insert_message(m)
                if mapped["kind"] == SPAN_KIND["TOOL_CALL"]:
                    tc = _extract_tool_call(mapped["id"], sp.attributes)
                    if tc:
                        store.insert_tool_call(tc)
                        tool_name = tc["tool_name"]
                # Replay cache (PRD 7.3): pin deterministic LLM responses.
                if mapped["kind"] == SPAN_KIND["LLM_CALL"] and mapped["prompt_hash"]:
                    resp = _get_str(sp.attributes, "gen_ai.completion.0.content")
                    if resp is not None:
                        store.upsert_llm_cache(
                            {
                                "prompt_hash": mapped["prompt_hash"],
                                "model": mapped["model"],
                                "response_ref": resp,
                                "tokens_in": mapped["tokens_in"],
                                "tokens_out": mapped["tokens_out"],
                                "captured_at": mapped["started_at"]
                                or datetime.utcnow(),
                            }
                        )
                # Breakpoint hit detection (PRD 9.5).
                if bps:
                    ctx = _bp_ctx(mapped, tool_name)
                    for bid, expr in bps:
                        try:
                            if bp.evaluate(expr, ctx):
                                store.record_breakpoint_hit(
                                    bid,
                                    mapped["id"],
                                    trace_id,
                                    datetime.utcnow(),
                                )
                        except Exception:
                            pass  # never break ingestion on a bad predicate
                span_count += 1
    return span_count
