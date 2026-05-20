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

from . import auth as authmod
from .tenancy import (
    create_tenant,
    resolve,
    store_for,
    tenant_api_key,
)

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
    # (Cloud Phase 3). Functional here for parity.
    s, lk = _store(t)
    return replay_branch(
        s,
        lk,
        body["source_trace_id"],
        body["branch_point_span_id"],
        body["mutation"],
    )


# ---- Cloud Phase 2: auth + share links ---------------------------------

def require_user(authorization: str | None = Header(default=None)) -> dict:
    """JWT-gated dependency for human-facing routes. Returns the claims."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing Bearer token")
    return authmod.verify_jwt(authorization.split(None, 1)[1])


@app.post("/auth/signup")
def signup(body: dict):
    """Create tenant + first user; return JWT + the tenant's OTLP API key."""
    email = (body or {}).get("email", "").strip().lower()
    password = (body or {}).get("password", "")
    if "@" not in email or len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail="email + password (>=8 chars) required",
        )
    if authmod.find_user_by_email(email):
        raise HTTPException(status_code=409, detail="email already registered")
    tenant_name = (body.get("tenant_name") or email.split("@")[0]).strip()
    t = create_tenant(tenant_name)
    user_id = authmod.create_user(email, password, t["tenant_id"], role="owner")
    token = authmod.issue_jwt(user_id, t["tenant_id"], "owner")
    return {
        "token": token,
        "user_id": user_id,
        "tenant_id": t["tenant_id"],
        "tenant_name": tenant_name,
        "api_key": t["api_key"],
        "email": email,
    }


@app.post("/auth/login")
def login(body: dict):
    email = (body or {}).get("email", "").strip().lower()
    password = (body or {}).get("password", "")
    u = authmod.find_user_by_email(email)
    if not u or not authmod.verify_password(password, u["password_hash"], u["pw_salt"]):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {
        "token": authmod.issue_jwt(u["id"], u["tenant_id"], u["role"]),
        "user_id": u["id"],
        "tenant_id": u["tenant_id"],
        "role": u["role"],
        "email": u["email"],
        "api_key": tenant_api_key(u["tenant_id"]),
    }


@app.get("/auth/me")
def me(claims: dict = Depends(require_user)):
    return {
        "user_id": claims["sub"],
        "tenant_id": claims["tid"],
        "role": claims.get("role", "member"),
        "exp": claims["exp"],
    }


@app.post("/traces/{trace_id}/share")
def create_share(trace_id: str, t: str = Depends(require_tenant)):
    """Mint a signed share link (PRD 4.11). The caller proves tenant ownership
    via the existing API key; the returned token is short, signed, and
    carries `{trace_id, tenant_id, exp}` so /share/{token} can serve it
    publicly without auth."""
    s, lk = _store(t)
    with lk:
        if not s.get_spans(trace_id):
            raise HTTPException(status_code=404, detail="trace not found")
    token = authmod.issue_share_token(trace_id, t)
    return {"token": token, "url": f"/share/{token}", "trace_id": trace_id}


@app.get("/share/{token}")
def fetch_share(token: str):
    """Public, read-only trace bundle behind a signed token."""
    claims = authmod.verify_share_token(token)
    tenant_id = claims["tid"]
    trace_id = claims["share"]
    s, lk = store_for(tenant_id)
    with lk:
        spans = s.get_spans(trace_id)
        if not spans:
            raise HTTPException(status_code=404, detail="trace not found")
        return s.export_trace(trace_id)
