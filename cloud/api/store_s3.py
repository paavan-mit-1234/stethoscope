"""S3 payload offload for the cloud store (PRD 4.11, Cloud Phase 2 promise).

Why: LLM completions + tool results can be tens of KB to MBs. Inlining them
in Postgres rows is fine at small scale but eats RDS storage and slows queries
once you have any volume. The fix is the same one the embedded ``crates/store``
uses with Parquet: keep cheap metadata inline, push the bytes to object
storage and store an opaque reference.

Design:

* This module is **storage-layer only** — the mapper and PgStore don't know
  about S3. The cloud entrypoint wraps ``PgStore`` with ``S3OffloadStore``
  (decorator) so writes spill to S3 and reads inline them back transparently.
* Threshold is env-driven (``STETHOSCOPE_S3_THRESHOLD``, default 16 KB) so the
  dev DuckDB path stays unaffected and unit tests can pin small thresholds.
* boto3 is loaded lazily — the duckdb-only dev image doesn't need it.

Configure via env (set in the Fargate task definition):
* ``STETHOSCOPE_S3_BUCKET`` — payloads bucket (Terraform creates this).
* ``STETHOSCOPE_S3_PREFIX`` — optional key prefix, default ``payloads/``.
* ``STETHOSCOPE_S3_THRESHOLD`` — int bytes; values larger than this go to S3.

Cost note: each PUT is ~$0.0004 in ap-south-1. At 1k spans/day with ~30%
exceeding the threshold, monthly S3 PUT cost is ~$0.04. GETs are cheaper.
The bucket has a lifecycle rule (Terraform) that moves objects to Glacier
after 90 days.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

_BUCKET = os.environ.get("STETHOSCOPE_S3_BUCKET", "")
_PREFIX = os.environ.get("STETHOSCOPE_S3_PREFIX", "payloads/")
_THRESHOLD = int(os.environ.get("STETHOSCOPE_S3_THRESHOLD", "16384"))  # 16 KB

_s3_client = None


def _client():
    """Lazy boto3 client (avoids a hard dep when offload is off)."""
    global _s3_client
    if _s3_client is None:
        import boto3  # pyright: ignore[reportMissingImports]

        _s3_client = boto3.client("s3")
    return _s3_client


def offload_enabled() -> bool:
    return bool(_BUCKET)


def _put(tenant_id: str, content: str) -> str:
    key = f"{_PREFIX}{tenant_id}/{uuid.uuid4().hex}"
    _client().put_object(
        Bucket=_BUCKET,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    return f"s3://{_BUCKET}/{key}"


def _get(s3_uri: str) -> str:
    # s3://bucket/key/with/slashes
    assert s3_uri.startswith("s3://")
    rest = s3_uri[len("s3://"):]
    bucket, _, key = rest.partition("/")
    obj = _client().get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8")


def _maybe_offload(tenant_id: str, content: str | None) -> tuple[str | None, str | None]:
    """Return ``(inline, ref)``. If ``content`` is over threshold and offload
    is enabled, push to S3 and return ``(None, s3://...)``. Otherwise keep
    inline."""
    if content is None or not offload_enabled() or len(content) <= _THRESHOLD:
        return content, None
    return None, _put(tenant_id, content)


def _maybe_inline(inline: str | None, ref: str | None) -> str | None:
    """Read path: prefer the inline copy; otherwise dereference S3."""
    if inline is not None:
        return inline
    if ref and ref.startswith("s3://"):
        return _get(ref)
    return None  # ref present but not S3 — unknown scheme; leave to caller


class S3OffloadStore:
    """Decorator around ``PgStore`` that transparently spills large payloads
    to S3 on write and dereferences them on read.

    Methods that don't touch payloads are delegated unchanged. The decorator
    only intercepts ``insert_message``, ``insert_tool_call``, ``upsert_llm_cache``
    on the write path and the message/tool/cache readers on the read path.
    """

    def __init__(self, inner, tenant_id: str):
        self._inner = inner
        self._t = tenant_id

    def __getattr__(self, name):
        return getattr(self._inner, name)

    # ---- writes -------------------------------------------------------

    def insert_message(self, m: dict[str, Any]) -> None:
        inline, ref = _maybe_offload(self._t, m.get("content_inline"))
        if ref is not None:
            m = {**m, "content_inline": inline, "content_ref": ref}
        self._inner.insert_message(m)

    def insert_tool_call(self, c: dict[str, Any]) -> None:
        c = dict(c)
        for field, ref_field in (
            ("arguments_inline", "arguments_ref"),
            ("result_inline", "result_ref"),
        ):
            inline, ref = _maybe_offload(self._t, c.get(field))
            if ref is not None:
                c[field] = inline
                c[ref_field] = ref
        self._inner.insert_tool_call(c)

    def upsert_llm_cache(self, payload: dict[str, Any]) -> None:
        # llm_cache.response_ref already holds the response (inline today).
        # If it crosses the threshold, push to S3 and store the s3:// uri.
        ref = payload.get("response_ref")
        inline, s3 = _maybe_offload(self._t, ref)
        if s3 is not None:
            payload = {**payload, "response_ref": s3}
        self._inner.upsert_llm_cache(payload)

    # ---- reads --------------------------------------------------------

    def get_messages(self, span_id: str) -> list[dict[str, Any]]:
        rows = self._inner.get_messages(span_id)
        for r in rows:
            r["content_inline"] = _maybe_inline(
                r.get("content_inline"), r.get("content_ref")
            )
        return rows

    def get_tool_call(self, span_id: str) -> dict[str, Any] | None:
        r = self._inner.get_tool_call(span_id)
        if r is None:
            return None
        r["arguments_inline"] = _maybe_inline(
            r.get("arguments_inline"), r.get("arguments_ref")
        )
        r["result_inline"] = _maybe_inline(
            r.get("result_inline"), r.get("result_ref")
        )
        return r

    def get_llm_cache(self, prompt_hash: str) -> dict[str, Any] | None:
        r = self._inner.get_llm_cache(prompt_hash)
        if r is None:
            return None
        ref = r.get("response_ref")
        if ref and ref.startswith("s3://"):
            r["response_ref"] = _get(ref)
        return r

    def export_trace(self, trace_id: str) -> dict[str, Any]:
        # The base implementation calls our overridden readers transitively
        # only if it routes through ``self``. PgStore.export_trace uses bare
        # ``self.get_messages`` which would skip our overrides — so we reuse
        # the same loop but on the wrapped object.
        spans = self.get_spans(trace_id)
        bundle: dict[str, Any] = {
            "steth_version": 1, "trace_id": trace_id, "spans": spans,
            "messages": {}, "tool_calls": {}, "llm_cache": {},
        }
        for s in spans:
            ms = self.get_messages(s["id"])
            if ms:
                bundle["messages"][s["id"]] = ms
            tc = self.get_tool_call(s["id"])
            if tc:
                bundle["tool_calls"][s["id"]] = tc
            if s.get("prompt_hash"):
                hit = self.get_llm_cache(s["prompt_hash"])
                if hit:
                    bundle["llm_cache"][s["prompt_hash"]] = hit
        return bundle
