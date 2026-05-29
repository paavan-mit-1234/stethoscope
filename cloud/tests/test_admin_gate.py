"""Prod-mode gates on /tenants. We don't actually start the API in prod
because the JWT secret would be required; instead we exercise the
``require_admin`` dependency directly with mocked env."""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi import HTTPException


def _reload_with(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    for mod in [m for m in list(sys.modules) if m.startswith("cloud.")]:
        del sys.modules[mod]
    return importlib.import_module("cloud.api.app")


def test_prod_without_admin_token_blocks_tenant_creation(monkeypatch, tmp_path):
    monkeypatch.setenv("STETHOSCOPE_CLOUD_DATA", str(tmp_path))
    monkeypatch.setenv("STETHOSCOPE_JWT_SECRET", "test-secret-32-chars-or-longer-aaa")
    monkeypatch.setenv("STETHOSCOPE_CORS_ORIGINS", "https://example.test")
    app_mod = _reload_with(
        monkeypatch,
        STETHOSCOPE_ENV="prod",
        STETHOSCOPE_ADMIN_TOKEN=None,
    )
    with pytest.raises(HTTPException) as exc:
        app_mod.require_admin(authorization=None)
    assert exc.value.status_code == 404


def test_prod_with_admin_token_requires_match(monkeypatch, tmp_path):
    monkeypatch.setenv("STETHOSCOPE_CLOUD_DATA", str(tmp_path))
    monkeypatch.setenv("STETHOSCOPE_JWT_SECRET", "test-secret-32-chars-or-longer-aaa")
    monkeypatch.setenv("STETHOSCOPE_CORS_ORIGINS", "https://example.test")
    app_mod = _reload_with(
        monkeypatch,
        STETHOSCOPE_ENV="prod",
        STETHOSCOPE_ADMIN_TOKEN="topsecret",
    )
    with pytest.raises(HTTPException) as exc:
        app_mod.require_admin(authorization=None)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        app_mod.require_admin(authorization="Bearer wrong")
    assert exc.value.status_code == 401

    # Correct token returns None (no raise).
    assert app_mod.require_admin(authorization="Bearer topsecret") is None


def test_prod_without_jwt_secret_refuses_to_boot(monkeypatch, tmp_path):
    monkeypatch.setenv("STETHOSCOPE_CLOUD_DATA", str(tmp_path))
    monkeypatch.delenv("STETHOSCOPE_JWT_SECRET", raising=False)
    monkeypatch.setenv("STETHOSCOPE_ENV", "prod")
    for mod in [m for m in list(sys.modules) if m.startswith("cloud.")]:
        del sys.modules[mod]
    with pytest.raises(RuntimeError, match="STETHOSCOPE_JWT_SECRET"):
        importlib.import_module("cloud.api.auth")


def test_prod_without_cors_refuses_to_boot(monkeypatch, tmp_path):
    monkeypatch.setenv("STETHOSCOPE_CLOUD_DATA", str(tmp_path))
    monkeypatch.setenv("STETHOSCOPE_JWT_SECRET", "test-secret-32-chars-or-longer-aaa")
    monkeypatch.setenv("STETHOSCOPE_ENV", "prod")
    monkeypatch.delenv("STETHOSCOPE_CORS_ORIGINS", raising=False)
    for mod in [m for m in list(sys.modules) if m.startswith("cloud.")]:
        del sys.modules[mod]
    with pytest.raises(RuntimeError, match="STETHOSCOPE_CORS_ORIGINS"):
        importlib.import_module("cloud.api.app")
