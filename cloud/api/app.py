"""Stethoscope Cloud API (Cloud Phase 1) — multi-tenant FastAPI.

Reuses the proven reference logic (tools/ref_ingest mapper/store,
tools/ref_replay) unchanged; adds tenant scoping + an OTLP/HTTP ingest
endpoint so agents can ship to the cloud with just an API key.

Run locally:
    pip install fastapi uvicorn
    uvicorn cloud.api.app:app --port 8080      # from repo root
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from tools.ref_ingest.mapper import ingest_request
from tools.ref_replay import branch as replay_branch

from .tenancy import create_tenant, resolve, store_for

app = FastAPI(title="Stethoscope Cloud", version="1.0.0")

# The browser Workbench (any origin in dev); tighten to the UI domain in prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_tenant(x_stethoscope_key: str | None = Header(default=None)) -> str:
    tid = resolve(x_stethoscope_key)
    if not tid:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return tid


def _json(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_json(x) for x in obj]
    return obj


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "stethoscope-cloud"}


@app.post("/tenants")
def post_tenant(body: dict) -> dict:
    # Cloud Phase 2: gate behind admin/Cognito. Open here for verification.
    name = (body or {}).get("name", "tenant")
    return create_tenant(name)


@app.post("/v1/traces")
async def otlp_ingest(request: Request, tenant: str = Depends(require_tenant)):
    """OTLP/HTTP trace ingest (protobuf body, OTel's standard path)."""
    raw = await request.body()
    req = ExportTraceServiceRequest()
    req.ParseFromString(raw)
    store, lock = store_for(tenant)
    with lock:
        ingest_request(store, req)
    return Response(
        content=ExportTraceServiceResponse().SerializeToString(),
        media_type="application/x-protobuf",
    )


# ---- read API (tenant-scoped; mirrors tools/ref_ingest/api.py) ---------

def _store(tenant: str):
    return store_for(tenant)


@app.get("/projects")
def projects(t: str = Depends(require_tenant)):
    s, lk = _store(t)
    with lk:
        return [{"id": i, "name": n} for i, n in s.list_projects()]


@app.get("/traces")
def traces(project_id: str | None = None, t: str = Depends(require_tenant)):
    s, lk = _store(t)
    with lk:
        return _json(s.list_traces(project_id))


@app.get("/traces/{trace_id}/spans")
def spans(trace_id: str, t: str = Depends(require_tenant)):
    s, lk = _store(t)
    with lk:
        return s.get_spans(trace_id)


@app.get("/spans/{span_id}")
def span(span_id: str, t: str = Depends(require_tenant)):
    s, lk = _store(t)
    with lk:
        return s.get_span(span_id)


@app.get("/spans/{span_id}/messages")
def messages(span_id: str, t: str = Depends(require_tenant)):
    s, lk = _store(t)
    with lk:
        return s.get_messages(span_id)


@app.get("/spans/{span_id}/tool_call")
def tool_call(span_id: str, t: str = Depends(require_tenant)):
    s, lk = _store(t)
    with lk:
        return s.get_tool_call(span_id)


@app.get("/breakpoints")
def list_bps(t: str = Depends(require_tenant)):
    s, lk = _store(t)
    with lk:
        return s.list_breakpoints()


@app.post("/breakpoints")
def add_bp(body: dict, t: str = Depends(require_tenant)):
    from tools.ref_ingest import bp

    dsl = (body or {}).get("condition_dsl", "")
    try:
        bp.parse(dsl)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"bad predicate: {exc}")
    s, lk = _store(t)
    with lk:
        projs = s.list_projects()
        pid = body.get("project_id") or (
            projs[0][0] if projs else s.ensure_project("default")
        )
        return {"id": s.add_breakpoint(pid, body.get("name"), dsl)}


@app.post("/breakpoints/delete")
def del_bp(body: dict, t: str = Depends(require_tenant)):
    s, lk = _store(t)
    with lk:
        s.delete_breakpoint(body["id"])
    return {"ok": True}


@app.get("/traces/{trace_id}/export")
def export(trace_id: str, t: str = Depends(require_tenant)):
    s, lk = _store(t)
    with lk:
        return s.export_trace(trace_id)


@app.post("/branch")
def branch(body: dict, t: str = Depends(require_tenant)):
    # Reference replay uses a subprocess; in cloud this becomes a worker/job
    # (Cloud Phase 2). Functional here for parity.
    s, lk = _store(t)
    return replay_branch(
        s,
        lk,
        body["source_trace_id"],
        body["branch_point_span_id"],
        body["mutation"],
    )
