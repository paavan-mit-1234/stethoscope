"""Test fixtures for the cloud API.

These tests run against the **DuckDB reference backend** (per-tenant files
under a temp directory) so they don't need a Postgres cluster — same path
as the local dev mode. Postgres-specific code paths (psycopg pool, schema
bootstrap, S3 offload) are covered by structural unit tests in
``test_tenancy.py`` without hitting AWS.
"""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture
def cloud_app(tmp_path, monkeypatch):
    """Fresh FastAPI app with isolated DuckDB state per test.

    Importing ``cloud.api.app`` triggers ``apply_schema_pg`` (no-op for
    duckdb) and reads env vars at import time, so we reset the modules
    after monkeypatching to make the env take effect.
    """
    monkeypatch.setenv("STETHOSCOPE_STORE", "duckdb")
    monkeypatch.setenv("STETHOSCOPE_CLOUD_DATA", str(tmp_path))
    monkeypatch.setenv("STETHOSCOPE_ENV", "dev")
    monkeypatch.delenv("STETHOSCOPE_JWT_SECRET", raising=False)
    monkeypatch.delenv("STETHOSCOPE_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("STETHOSCOPE_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("STETHOSCOPE_SQS_QUEUE_URL", raising=False)
    monkeypatch.delenv("STETHOSCOPE_S3_BUCKET", raising=False)

    # Drop any cached cloud.* modules so the env above takes effect.
    for mod in [m for m in list(sys.modules) if m.startswith("cloud.")]:
        del sys.modules[mod]

    app_module = importlib.import_module("cloud.api.app")
    return app_module.app


@pytest.fixture
def client(cloud_app):
    from fastapi.testclient import TestClient

    with TestClient(cloud_app) as c:
        yield c
