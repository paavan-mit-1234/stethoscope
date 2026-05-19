"""Multi-tenant resolution for the cloud API (Cloud Phase 1).

Local/verifiable reference: a control DuckDB holds the tenant registry, and
each tenant gets its own DuckDB trace store file (structural isolation —
mirrors the PRD "single file per project", scaled to per-tenant). This
reuses tools/ref_ingest.store.Store unchanged, so every existing capability
(mapper, breakpoints, replay, .steth export) works per-tenant for free.

Cloud canon: the same logical model with a `tenant_id` column on every row
in Postgres (see store_pg.py + schema_pg.sql). The API layer is identical;
only the Store implementation swaps.
"""

from __future__ import annotations

import os
import secrets
import threading

import duckdb

from tools.ref_ingest.ids import ulid
from tools.ref_ingest.store import Store

DATA_ROOT = os.environ.get(
    "STETHOSCOPE_CLOUD_DATA",
    os.path.join(os.path.expanduser("~"), ".stethoscope-cloud"),
)

_control_lock = threading.Lock()
_control: duckdb.DuckDBPyConnection | None = None
# tenant_id -> (Store, Lock); duckdb connections are single-threaded.
_stores: dict[str, tuple[Store, threading.Lock]] = {}
_stores_guard = threading.Lock()


def _control_con() -> duckdb.DuckDBPyConnection:
    global _control
    if _control is None:
        os.makedirs(DATA_ROOT, exist_ok=True)
        _control = duckdb.connect(os.path.join(DATA_ROOT, "_control.db"))
        _control.execute(
            """CREATE TABLE IF NOT EXISTS tenants (
                 id VARCHAR PRIMARY KEY,
                 name VARCHAR NOT NULL,
                 api_key VARCHAR NOT NULL UNIQUE,
                 created_at TIMESTAMP NOT NULL DEFAULT now()
               )"""
        )
    return _control


def create_tenant(name: str) -> dict[str, str]:
    """Register a tenant, return its id + freshly minted API key.

    Cloud (Phase 2): gate this behind admin auth / Cognito. Open here so the
    local verification can provision tenants.
    """
    tid = ulid()
    key = "sk_steth_" + secrets.token_urlsafe(24)
    with _control_lock:
        _control_con().execute(
            "INSERT INTO tenants (id, name, api_key) VALUES (?,?,?)",
            [tid, name, key],
        )
    return {"tenant_id": tid, "api_key": key}


def resolve(api_key: str | None) -> str | None:
    """API key -> tenant_id, or None if unknown/missing."""
    if not api_key:
        return None
    with _control_lock:
        row = _control_con().execute(
            "SELECT id FROM tenants WHERE api_key = ? LIMIT 1", [api_key]
        ).fetchone()
    return row[0] if row else None


def store_for(tenant_id: str) -> tuple[Store, threading.Lock]:
    """Per-tenant Store + its serialization lock (created on first use)."""
    with _stores_guard:
        if tenant_id not in _stores:
            path = os.path.join(DATA_ROOT, "tenants", tenant_id, "traces.db")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _stores[tenant_id] = (Store.open(path), threading.Lock())
        return _stores[tenant_id]
