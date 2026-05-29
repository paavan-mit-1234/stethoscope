"""Multi-tenant resolution for the cloud API.

Two backends, selected by ``STETHOSCOPE_STORE``:

* ``duckdb`` (default, local/reference) — per-tenant DuckDB file. Reuses
  ``tools/ref_ingest.store.Store`` unchanged.
* ``postgres`` (AWS canon, set by the prod Dockerfile) — single Postgres
  cluster, every row scoped by ``tenant_id`` via ``PgStore``.

The API never sees the difference: it always asks for ``store_for(tenant_id)``
and gets back ``(store, lock)``. In Postgres mode the "lock" is a no-op (DB
handles concurrency); in DuckDB mode it serializes the single connection.
"""

from __future__ import annotations

import os
import pathlib
import secrets
import threading
from typing import Protocol

import duckdb

from tools.ref_ingest.ids import ulid
from tools.ref_ingest.store import Store as DuckStore

# ---- backend selection ----------------------------------------------------

_STORE_KIND = os.environ.get("STETHOSCOPE_STORE", "duckdb").lower()
_DB_URL = os.environ.get("STETHOSCOPE_DATABASE_URL", "")

DATA_ROOT = os.environ.get(
    "STETHOSCOPE_CLOUD_DATA",
    os.path.join(os.path.expanduser("~"), ".stethoscope-cloud"),
)


def _is_postgres() -> bool:
    return _STORE_KIND == "postgres"


# ---- locks / control connection ------------------------------------------

_control_lock = threading.Lock()
control_lock = _control_lock  # re-export so auth.py uses the same lock

_duck_control: duckdb.DuckDBPyConnection | None = None
_pg_pool = None  # psycopg_pool.ConnectionPool, lazily imported
_pool_lock = threading.Lock()

# In DuckDB mode each tenant gets its own connection (DuckDB is single-thread).
# In Postgres mode we pool one cluster and check out per request.
_duck_stores: dict[str, tuple[DuckStore, threading.Lock]] = {}
_stores_guard = threading.Lock()

_NOOP_LOCK = threading.Lock()  # released immediately in Postgres mode


# ---- Postgres pool --------------------------------------------------------

def _pg_pool_or_init():
    """Lazy psycopg pool. Raises if STETHOSCOPE_DATABASE_URL is missing."""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pool_lock:
        if _pg_pool is not None:
            return _pg_pool
        if not _DB_URL:
            raise RuntimeError(
                "STETHOSCOPE_STORE=postgres requires STETHOSCOPE_DATABASE_URL"
            )
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover — prod image installs it
            raise RuntimeError(
                "psycopg_pool not installed; add psycopg[binary,pool] to deps"
            ) from exc
        _pg_pool = ConnectionPool(
            conninfo=_DB_URL,
            min_size=1,
            max_size=int(os.environ.get("STETHOSCOPE_PG_POOL_MAX", "10")),
            kwargs={"autocommit": False},
        )
        return _pg_pool


def apply_schema_pg() -> None:
    """Idempotent — schema_pg.sql uses CREATE TABLE IF NOT EXISTS. Called on
    app startup so a fresh RDS cluster bootstraps without a manual psql step."""
    if not _is_postgres():
        return
    sql = (pathlib.Path(__file__).with_name("schema_pg.sql")).read_text()
    pool = _pg_pool_or_init()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


# ---- DuckDB control DB (only used in duckdb mode) -------------------------

def _duck_control_con() -> duckdb.DuckDBPyConnection:
    global _duck_control
    if _duck_control is None:
        os.makedirs(DATA_ROOT, exist_ok=True)
        _duck_control = duckdb.connect(os.path.join(DATA_ROOT, "_control.db"))
        _duck_control.execute(
            """CREATE TABLE IF NOT EXISTS tenants (
                 id VARCHAR PRIMARY KEY,
                 name VARCHAR NOT NULL,
                 api_key VARCHAR NOT NULL UNIQUE,
                 created_at TIMESTAMP NOT NULL DEFAULT now()
               )"""
        )
        _duck_control.execute(
            """CREATE TABLE IF NOT EXISTS users (
                 id VARCHAR PRIMARY KEY,
                 tenant_id VARCHAR NOT NULL,
                 email VARCHAR NOT NULL UNIQUE,
                 password_hash VARCHAR NOT NULL,
                 pw_salt VARCHAR NOT NULL,
                 role VARCHAR NOT NULL DEFAULT 'member',
                 created_at TIMESTAMP NOT NULL DEFAULT now()
               )"""
        )
    return _duck_control


class _ControlAdapter(Protocol):
    """Minimum surface auth.py needs. Both backends provide an
    ``execute(sql, params)`` that returns something with ``.fetchone()``."""

    def execute(self, sql: str, params: list): ...


class _PgControlAdapter:
    """Make psycopg cursors look like duckdb's connection.execute API.

    The DuckDB control connection uses ``?`` placeholders; psycopg uses
    ``%s``. auth.py issues a small fixed set of queries — we translate.
    """

    def execute(self, sql: str, params: list):
        pg_sql = sql.replace("?", "%s")
        pool = _pg_pool_or_init()
        # Cursor must outlive this call (caller does .fetchone()), so we hold
        # the connection open and return the cursor; caller closes implicitly
        # by discarding. For writes we commit before returning.
        conn = pool.getconn()
        cur = conn.cursor()
        try:
            cur.execute(pg_sql, params)
            if pg_sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                conn.commit()
            return _CursorReleaser(cur, conn, pool)
        except Exception:
            conn.rollback()
            pool.putconn(conn)
            raise


class _CursorReleaser:
    """Returns the cursor's row(s); puts the connection back in the pool."""

    def __init__(self, cur, conn, pool):
        self._cur, self._conn, self._pool = cur, conn, pool

    def fetchone(self):
        try:
            return self._cur.fetchone()
        finally:
            self._release()

    def fetchall(self):
        try:
            return self._cur.fetchall()
        finally:
            self._release()

    def _release(self):
        try:
            self._cur.close()
        finally:
            self._pool.putconn(self._conn)


def control_connection() -> _ControlAdapter:
    """auth.py + tenant CRUD use this. In DuckDB mode it's the control con;
    in Postgres mode it's a thin adapter that translates ``?`` → ``%s`` and
    releases pooled connections after each query."""
    if _is_postgres():
        return _PgControlAdapter()
    return _duck_control_con()


# ---- tenant CRUD ----------------------------------------------------------

def create_tenant(name: str) -> dict[str, str]:
    """Register a tenant, return its id + freshly minted API key."""
    tid = ulid()
    key = "sk_steth_" + secrets.token_urlsafe(24)
    sql = "INSERT INTO tenants (id, name, api_key) VALUES (?, ?, ?)"
    with _control_lock:
        cur = control_connection().execute(sql, [tid, name, key])
        # In postgres mode the adapter committed already; in duckdb the
        # connection auto-commits. Either way: we only care it didn't raise.
        if hasattr(cur, "_release"):
            cur._release()
    return {"tenant_id": tid, "api_key": key}


def tenant_api_key(tenant_id: str) -> str | None:
    with _control_lock:
        row = control_connection().execute(
            "SELECT api_key FROM tenants WHERE id = ? LIMIT 1", [tenant_id]
        ).fetchone()
    return row[0] if row else None


def resolve(api_key: str | None) -> str | None:
    """API key -> tenant_id, or None if unknown/missing."""
    if not api_key:
        return None
    with _control_lock:
        row = control_connection().execute(
            "SELECT id FROM tenants WHERE api_key = ? LIMIT 1", [api_key]
        ).fetchone()
    return row[0] if row else None


# ---- per-tenant trace store ----------------------------------------------

def store_for(tenant_id: str):
    """Return ``(store, lock)`` for the given tenant.

    * Postgres: a fresh ``PgStore`` bound to the tenant and a no-op lock
      (Postgres handles concurrency; the API need not serialize).
    * DuckDB: the cached per-tenant ``Store`` + its serialization lock.
    """
    if _is_postgres():
        # Lazy import — PgStore needs psycopg which the duckdb-only image
        # doesn't ship.
        from . import store_s3
        from .store_pg import PgStore  # noqa: F401  (forces import for _PooledPgStore)

        pool = _pg_pool_or_init()
        conn = pool.getconn()
        # Wrap so the API's `with lock:` releases the connection back to the
        # pool when the request finishes.
        store = _PooledPgStore(conn, tenant_id, pool)
        # When STETHOSCOPE_S3_BUCKET is set, large payloads spill to S3 and
        # are dereferenced on read. Otherwise this wrapper is a no-op.
        if store_s3.offload_enabled():
            store = store_s3.S3OffloadStore(store, tenant_id)
        return store, _PooledReleaseLock(conn, pool)
    with _stores_guard:
        if tenant_id not in _duck_stores:
            path = os.path.join(DATA_ROOT, "tenants", tenant_id, "traces.db")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _duck_stores[tenant_id] = (DuckStore.open(path), threading.Lock())
        return _duck_stores[tenant_id]


class _PooledPgStore:
    """Wrap PgStore so we can release the connection after each request.

    PgStore.__init__ takes (conn, tenant); we just delegate every call to
    the underlying instance. The API code calls ``with lock: s.method(...)``,
    which is when we want to give the connection back.
    """

    def __init__(self, conn, tenant_id, pool):
        from .store_pg import PgStore

        self._impl = PgStore(conn, tenant_id)
        self._conn = conn
        self._pool = pool

    def __getattr__(self, name):
        return getattr(self._impl, name)


class _PooledReleaseLock:
    """Context manager that yields once, then puts the pg connection back."""

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._inner = threading.Lock()

    def __enter__(self):
        self._inner.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None:
                self._conn.rollback()
            else:
                self._conn.commit()
        finally:
            self._pool.putconn(self._conn)
            self._inner.release()

    # Some call sites use the lock without `with`; provide acquire/release
    # so older code paths still work (they just won't auto-release the conn).
    def acquire(self, *a, **kw):
        return self._inner.acquire(*a, **kw)

    def release(self):
        return self._inner.release()
