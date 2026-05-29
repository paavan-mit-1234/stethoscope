"""End-to-end-ish tests for the cloud API on the DuckDB reference backend.

Covers: health, tenant CRUD, OTLP ingest, tenant isolation, auth
(signup/login/me), share-link round-trip. Postgres- and AWS-specific paths
have their own structural tests in ``test_tenancy.py``.
"""

from __future__ import annotations

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.trace.v1.trace_pb2 import (
    ResourceSpans, ScopeSpans, Span,
)


def _sample_otlp() -> bytes:
    """Smallest valid OTLP payload — one root span, no attributes."""
    span = Span(
        trace_id=b"\x11" * 16,
        span_id=b"\x01" * 8,
        name="agent-run",
        start_time_unix_nano=1_000_000_000,
        end_time_unix_nano=2_000_000_000,
    )
    req = ExportTraceServiceRequest(
        resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[span])])]
    )
    return req.SerializeToString()


def test_health_is_open(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["env"] == "dev"


def test_tenants_open_in_dev(client):
    r = client.post("/tenants", json={"name": "acme"})
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"]
    assert body["api_key"].startswith("sk_steth_")


def test_otlp_ingest_requires_key(client):
    r = client.post(
        "/v1/traces",
        content=_sample_otlp(),
        headers={"content-type": "application/x-protobuf"},
    )
    assert r.status_code == 401


def test_otlp_round_trip(client):
    t = client.post("/tenants", json={"name": "rt"}).json()
    key = t["api_key"]

    r = client.post(
        "/v1/traces",
        content=_sample_otlp(),
        headers={
            "content-type": "application/x-protobuf",
            "x-stethoscope-key": key,
        },
    )
    assert r.status_code == 200

    traces = client.get("/traces", headers={"x-stethoscope-key": key}).json()
    assert len(traces) == 1
    assert traces[0]["span_count"] == 1


def test_tenant_isolation(client):
    a = client.post("/tenants", json={"name": "a"}).json()
    b = client.post("/tenants", json={"name": "b"}).json()

    client.post(
        "/v1/traces",
        content=_sample_otlp(),
        headers={
            "content-type": "application/x-protobuf",
            "x-stethoscope-key": a["api_key"],
        },
    )

    a_traces = client.get("/traces", headers={"x-stethoscope-key": a["api_key"]}).json()
    b_traces = client.get("/traces", headers={"x-stethoscope-key": b["api_key"]}).json()
    assert len(a_traces) == 1
    assert b_traces == []


def test_signup_login_me(client):
    s = client.post(
        "/auth/signup",
        json={"email": "p@example.com", "password": "hunter2hunter2"},
    ).json()
    assert s["token"] and s["api_key"] and s["tenant_id"]

    lg = client.post(
        "/auth/login",
        json={"email": "p@example.com", "password": "hunter2hunter2"},
    ).json()
    assert lg["token"]

    me = client.get(
        "/auth/me", headers={"authorization": f"Bearer {lg['token']}"}
    ).json()
    assert me["user_id"] == s["user_id"]
    assert me["tenant_id"] == s["tenant_id"]


def test_signup_rejects_weak_password(client):
    r = client.post(
        "/auth/signup", json={"email": "x@y.z", "password": "short"}
    )
    assert r.status_code == 400


def test_login_rejects_wrong_password(client):
    client.post(
        "/auth/signup",
        json={"email": "p@example.com", "password": "hunter2hunter2"},
    )
    r = client.post(
        "/auth/login",
        json={"email": "p@example.com", "password": "wrongguess"},
    )
    assert r.status_code == 401


def test_share_link_round_trip(client):
    t = client.post("/tenants", json={"name": "share"}).json()
    key = t["api_key"]
    client.post(
        "/v1/traces",
        content=_sample_otlp(),
        headers={
            "content-type": "application/x-protobuf",
            "x-stethoscope-key": key,
        },
    )
    traces = client.get("/traces", headers={"x-stethoscope-key": key}).json()
    trace_id = traces[0]["id"]

    share = client.post(
        f"/traces/{trace_id}/share",
        headers={"x-stethoscope-key": key},
    ).json()
    assert share["token"]

    bundle = client.get(share["url"]).json()
    assert bundle["trace_id"] == trace_id
    assert len(bundle["spans"]) == 1
