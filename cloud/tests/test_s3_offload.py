"""S3 offload decorator — no real S3 calls; we stub put/get."""

from __future__ import annotations

import importlib
import sys


def _fresh_store_s3(monkeypatch, threshold=10, bucket="testbucket"):
    monkeypatch.setenv("STETHOSCOPE_S3_BUCKET", bucket)
    monkeypatch.setenv("STETHOSCOPE_S3_PREFIX", "p/")
    monkeypatch.setenv("STETHOSCOPE_S3_THRESHOLD", str(threshold))
    sys.modules.pop("cloud.api.store_s3", None)
    return importlib.import_module("cloud.api.store_s3")


class _InMemoryInner:
    """Pretend PgStore — keeps its inserts in memory for assertions."""

    def __init__(self):
        self.messages: list[dict] = []
        self.tool_calls: list[dict] = []
        self.llm_cache: list[dict] = []
        self.spans: list[dict] = [{
            "id": "spn1", "prompt_hash": "h1", "trace_id": "trc1",
        }]

    def insert_message(self, m): self.messages.append(m)
    def insert_tool_call(self, c): self.tool_calls.append(c)
    def upsert_llm_cache(self, c): self.llm_cache.append(c)
    def get_spans(self, _): return self.spans
    def get_messages(self, _): return list(self.messages)
    def get_tool_call(self, _): return self.tool_calls[-1] if self.tool_calls else None
    def get_llm_cache(self, _): return self.llm_cache[-1] if self.llm_cache else None


def test_small_payloads_stay_inline(monkeypatch):
    s3 = _fresh_store_s3(monkeypatch, threshold=1024)
    inner = _InMemoryInner()
    wrapped = s3.S3OffloadStore(inner, tenant_id="t1")

    wrapped.insert_message({"id": "m1", "span_id": "s1", "seq": 0,
                            "role": "user", "content_inline": "small"})
    assert inner.messages[0]["content_inline"] == "small"
    assert inner.messages[0].get("content_ref") is None


def test_large_payload_offloaded(monkeypatch):
    s3 = _fresh_store_s3(monkeypatch, threshold=10)

    puts: dict[str, str] = {}

    class FakeClient:
        def put_object(self, Bucket, Key, Body, **_):
            puts[Key] = Body.decode("utf-8")

        def get_object(self, Bucket, Key):
            return {"Body": _FakeBody(puts[Key].encode("utf-8"))}

    class _FakeBody:
        def __init__(self, b): self._b = b
        def read(self): return self._b

    monkeypatch.setattr(s3, "_s3_client", FakeClient())

    inner = _InMemoryInner()
    wrapped = s3.S3OffloadStore(inner, tenant_id="t1")
    big = "X" * 256

    wrapped.insert_message({"id": "m1", "span_id": "s1", "seq": 0,
                            "role": "user", "content_inline": big})
    inserted = inner.messages[0]
    assert inserted["content_inline"] is None
    assert inserted["content_ref"].startswith("s3://testbucket/p/t1/")

    # Read path inlines from the fake S3.
    rows = wrapped.get_messages("s1")
    assert rows[0]["content_inline"] == big


def test_disabled_offload_passes_through(monkeypatch):
    monkeypatch.delenv("STETHOSCOPE_S3_BUCKET", raising=False)
    sys.modules.pop("cloud.api.store_s3", None)
    s3 = importlib.import_module("cloud.api.store_s3")

    assert s3.offload_enabled() is False
    inner = _InMemoryInner()
    wrapped = s3.S3OffloadStore(inner, tenant_id="t")
    wrapped.insert_message({"id": "m1", "span_id": "s", "seq": 0,
                            "role": "user", "content_inline": "X" * 9_999_999})
    assert inner.messages[0]["content_inline"] == "X" * 9_999_999
