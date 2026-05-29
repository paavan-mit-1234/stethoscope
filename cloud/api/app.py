"""Stethoscope Cloud API — multi-tenant FastAPI (production target).

Reuses the proven reference logic (tools/ref_ingest mapper/store,
tools/ref_replay) unchanged; adds tenant scoping, env-driven backends,
hardened defaults for the Fargate deployment.

Env switches the API honours (set by the ECS task definition):

* ``STETHOSCOPE_ENV``: ``dev`` (default) or ``prod`` — gates dangerous
  defaults like open-tenant-creation and ephemeral JWT secrets.
* ``STETHOSCOPE_STORE``: ``duckdb`` (dev) or ``postgres`` (prod).
* ``STETHOSCOPE_DATABASE_URL``: RDS URL (Secrets Manager → task secret).
* ``STETHOSCOPE_JWT_SECRET``: signing secret (Secrets Manager → task secret).
* ``STETHOSCOPE_CORS_ORIGINS``: comma-separated allowlist; default ``*`` in
  dev only. In prod the missing value is fatal — set it to the UI URL.
* ``STETHOSCOPE_ADMIN_TOKEN``: shared secret to call ``/tenants``. If unset
  *and* ``STETHOSCOPE_ENV=prod``, ``/tenants`` returns 404.
* ``STETHOSCOPE_SQS_QUEUE_URL``: when set, ``/branch`` enqueues; otherwise it
  returns 501 with a pointer to the desktop app.
* ``STETHOSCOPE_S3_BUCKET``: when set, payloads over the threshold spill to
  S3 (see ``store_s3.py``).

Run locally::

    pip install fastapi uvicorn 'psycopg[binary,pool]' boto3
    uvicorn cloud.api.app:app --port 8080   # from repo root
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from tools.ref_ingest.mapper import ingest_request

from . import auth as authmod
from .tenancy import (
    apply_schema_pg,
    create_tenant,
    resolve,
    store_for,
    tenant_api_key,
)

log = logging.getLogger("stethoscope.api")
ENV = os.environ.get("STETHOSCOPE_ENV", "dev").lower()
IS_PROD = ENV == "prod"
ADMIN_TOKEN = os.environ.get("STETHOSCOPE_ADMIN_TOKEN", "")
SQS_QUEUE_URL = os.environ.get("STETHOSCOPE_SQS_QUEUE_URL", "")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """Apply the Postgres schema once on first boot (idempotent CREATE IF
    NOT EXISTS). No-op in DuckDB mode. Failing this is fatal — we'd rather
    crash the container than serve traffic against an unmigrated schema."""
    apply_schema_pg()
    log.info(
        "stethoscope api up env=%s store=%s sqs=%s s3=%s",
        ENV,
        os.environ.get("STETHOSCOPE_STORE", "duckdb"),
        bool(SQS_QUEUE_URL),
        bool(os.environ.get("STETHOSCOPE_S3_BUCKET")),
    )
    yield


app = FastAPI(title="Stethoscope Cloud", version="1.0.0", lifespan=lifespan)


def _cors_origins() -> list[str]:
    """Drive CORS from env. In prod the var is required; in dev we allow ``*``
    as a convenience (browser dev server hits localhost:8080)."""
    raw = os.environ.get("STETHOSCOPE_CORS_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if IS_PROD:
        raise RuntimeError(
            "STETHOSCOPE_CORS_ORIGINS is required when STETHOSCOPE_ENV=prod"
        )
    return ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,  # bearer + api-key are not cookies
)


# ---- deps ------------------------------------------------------------------

def require_tenant(x_stethoscope_key: str | None = Header(default=None)) -> str:
    tid = resolve(x_stethoscope_key)
    if not tid:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return tid


def require_admin(authorization: str | None = Header(default=None)) -> None:
    """Tenant creation must be guarded in prod. In dev we still require the
    header but accept an empty admin token configuration as a no-op gate."""
    if not IS_PROD and not ADMIN_TOKEN:
        return
    if not ADMIN_TOKEN:
        # prod + no admin token configured — the route is unreachable.
        raise HTTPException(status_code=404, detail="not found")
    expected = f"bearer {ADMIN_TOKEN}".lower()
    if not authorization or authorization.lower() != expected:
        raise HTTPException(status_code=401, detail="admin token required")


def _json(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_json(x) for x in obj]
    return obj


# ---- health ---------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Cheap liveness probe — used by the ALB target group."""
    return {"ok": True, "service": "stethoscope-cloud", "env": ENV}


@app.get("/health/deep")
def health_deep() -> dict:
    """Readiness probe — touches the DB so a broken connection 503s."""
    from .tenancy import _is_postgres, _pg_pool_or_init  # local-only helpers

    db_ok = True
    db_err: str | None = None
    if _is_postgres():
        try:
            pool = _pg_pool_or_init()
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
        except Exception as exc:
            db_ok = False
            db_err = str(exc)
    return {"ok": db_ok, "db_error": db_err, "env": ENV}


# ---- tenants (admin-gated in prod) ----------------------------------------

@app.post("/tenants", dependencies=[Depends(require_admin)])
def post_tenant(body: dict) -> dict:
    """Mint a tenant + API key. In prod requires ``Authorization: Bearer
    <STETHOSCOPE_ADMIN_TOKEN>``; in dev it's open."""
    name = (body or {}).get("name", "tenant")
    return create_tenant(name)


# ---- OTLP ingest ----------------------------------------------------------

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


# ---- read API (tenant-scoped) --------------------------------------------

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


# ---- branch / replay ------------------------------------------------------

@app.post("/branch")
def branch(body: dict, t: str = Depends(require_tenant)):
    """Branch + replay a trace.

    Two modes:

    * **Local/desktop** (no ``STETHOSCOPE_SQS_QUEUE_URL``) — runs the
      subprocess-based reference replay in-process. Works when the API and
      the agent code live on the same machine (dev, single-tenant).
    * **Cloud worker** (queue configured) — enqueues a replay job. A worker
      pulls it; see ``cloud/api/worker.py`` for the (currently stubbed)
      execution model. The HTTP response acknowledges the enqueue; the new
      branch trace arrives later via the normal ingest path.

    Cloud Phase 1 honestly returns 501 from the worker because the cloud
    can't run the customer's agent — see RUNBOOK §replay for the deferral
    rationale and the migration plan.
    """
    if SQS_QUEUE_URL:
        import boto3  # pyright: ignore[reportMissingImports]

        s, lk = _store(t)
        with lk:
            if not s.get_spans(body["source_trace_id"]):
                raise HTTPException(status_code=404, detail="trace not found")
        sqs = boto3.client("sqs")
        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps({
                "tenant_id": t,
                "source_trace_id": body["source_trace_id"],
                "branch_point_span_id": body["branch_point_span_id"],
                "mutation": body["mutation"],
            }),
        )
        return {
            "ok": True,
            "queued": True,
            "note": (
                "replay queued; worker execution is not implemented in cloud "
                "Phase 1 (see RUNBOOK §replay). Use the desktop app for "
                "interactive replay."
            ),
        }
    # Local/desktop fallback — only safe when API + agent share a filesystem.
    from tools.ref_replay import branch as replay_branch

    s, lk = _store(t)
    return replay_branch(
        s,
        lk,
        body["source_trace_id"],
        body["branch_point_span_id"],
        body["mutation"],
    )


# ---- auth (signup / login / share) ----------------------------------------

def require_user(authorization: str | None = Header(default=None)) -> dict:
    """JWT-gated dependency for human-facing routes. Returns the claims."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing Bearer token")
    return authmod.verify_jwt(authorization.split(None, 1)[1])


@app.post("/auth/signup")
def signup(body: dict):
    """Create tenant + first user; return JWT + tenant's OTLP API key.

    Self-signup is open by design — the rate-limiting story (Cloud Phase 3)
    is a WAF/Cognito throttle in front of this endpoint, not app-level."""
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
    """Mint a signed share link. The caller proves tenant ownership via the
    existing API key; the returned token is short, signed, and carries
    ``{trace_id, tenant_id, exp}`` so ``/share/{token}`` can serve it
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
