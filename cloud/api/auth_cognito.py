"""Cognito canonical auth adapter (Cloud Phase 2 — AWS deploy target).

Swap into `auth.verify_jwt` by setting `STETHOSCOPE_AUTH=cognito` and
`COGNITO_REGION` + `COGNITO_USER_POOL_ID` + `COGNITO_CLIENT_ID`. The
local HS256 path stays as the reference for environments without Cognito.

Cognito issues RS256 JWTs signed by keys published at JWKS:
    https://cognito-idp.<region>.amazonaws.com/<user_pool_id>/.well-known/jwks.json

This module fetches + caches the JWKS by `kid`, verifies the token, and
normalizes the claim shape (Cognito's `sub` -> `user_id`, the configurable
custom attribute `custom:tenant_id` -> `tenant_id`, optional
`cognito:groups[0]` -> `role`) so callers of `verify_jwt` see the same dict
shape as the local HS256 path.

NOT executed in this build (no AWS / Cognito here) — same status as the
uncompiled Rust crates. Verified by structure; deploy + integration-test
from a machine pointed at a real user pool.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm

REGION = os.environ.get("COGNITO_REGION", "us-east-1")
USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
_TENANT_CLAIM = os.environ.get("COGNITO_TENANT_CLAIM", "custom:tenant_id")

_JWKS_TTL = 3600
_jwks_lock = threading.Lock()
_jwks_cache: dict[str, object] = {"fetched_at": 0.0, "keys": {}}


def _jwks_url() -> str:
    return (
        f"https://cognito-idp.{REGION}.amazonaws.com/"
        f"{USER_POOL_ID}/.well-known/jwks.json"
    )


def _issuer() -> str:
    return f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"


def _get_jwk(kid: str):
    with _jwks_lock:
        now = time.time()
        if (
            now - float(_jwks_cache["fetched_at"]) > _JWKS_TTL
            or kid not in _jwks_cache["keys"]  # type: ignore[operator]
        ):
            with urllib.request.urlopen(_jwks_url(), timeout=5) as r:
                doc = json.load(r)
            _jwks_cache["fetched_at"] = now
            _jwks_cache["keys"] = {k["kid"]: k for k in doc.get("keys", [])}
        return _jwks_cache["keys"].get(kid)  # type: ignore[union-attr]


def verify_cognito_jwt(token: str) -> dict:
    """Verify a Cognito-issued JWT and return normalized claims:
    `{sub: user_id, tid: tenant_id, role: <group or 'member'>, exp: ...}`."""
    header = pyjwt.get_unverified_header(token)
    jwk = _get_jwk(header["kid"])
    if jwk is None:
        raise ValueError("unknown signing key id")
    pub_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
    claims = pyjwt.decode(
        token,
        key=pub_key,
        algorithms=["RS256"],
        audience=CLIENT_ID or None,
        issuer=_issuer(),
        options={"require": ["exp", "iat", "sub"]},
    )
    role = "member"
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, list) and groups:
        role = str(groups[0])
    return {
        "sub": claims["sub"],
        "tid": claims.get(_TENANT_CLAIM, ""),
        "role": role,
        "exp": claims["exp"],
        "iat": claims.get("iat"),
        "_raw": claims,
    }
