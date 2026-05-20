"""Cloud Phase 2 — auth.

Local reference: users in the control DB; PBKDF2 password hashing; HS256 JWT
issued by `/auth/signup` and `/auth/login`. The canonical AWS path is
Cognito (`auth_cognito.py`) — same `require_user` shape, different backend.

The OTLP ingestion endpoint keeps the long-lived `X-Stethoscope-Key` tenant
API key (programmatic agent auth, standard SaaS pattern); JWTs are for the
human-facing UI/read API.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import jwt as pyjwt
from fastapi import HTTPException

from tools.ref_ingest.ids import ulid

from .tenancy import control_connection, control_lock

_PBKDF2_ITERS = 200_000
_JWT_ALGO = "HS256"
_JWT_TTL = 24 * 3600

# Server signing secret. Set STETHOSCOPE_JWT_SECRET in production (Secrets
# Manager). The fallback random secret means sessions don't survive restart,
# which is intentional for dev — set the env var to persist.
_JWT_SECRET = os.environ.get("STETHOSCOPE_JWT_SECRET") or secrets.token_urlsafe(32)


# ---- password hashing (PBKDF2-HMAC-SHA256) -----------------------------

def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return h.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    h = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ITERS
    )
    # constant-time compare
    return hmac.compare_digest(h.hex(), hash_hex)


# ---- users -------------------------------------------------------------

def find_user_by_email(email: str) -> dict | None:
    with control_lock:
        row = control_connection().execute(
            "SELECT id, tenant_id, email, password_hash, pw_salt, role "
            "FROM users WHERE email = ? LIMIT 1",
            [email.lower().strip()],
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0], "tenant_id": row[1], "email": row[2],
        "password_hash": row[3], "pw_salt": row[4], "role": row[5],
    }


def create_user(email: str, password: str, tenant_id: str, role: str = "member") -> str:
    uid = ulid()
    pw_hash, pw_salt = hash_password(password)
    with control_lock:
        control_connection().execute(
            """INSERT INTO users (id, tenant_id, email, password_hash, pw_salt, role)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [uid, tenant_id, email.lower().strip(), pw_hash, pw_salt, role],
        )
    return uid


# ---- JWT --------------------------------------------------------------

def issue_jwt(user_id: str, tenant_id: str, role: str) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "tid": tenant_id,
        "role": role,
        "iat": now,
        "exp": now + _JWT_TTL,
    }
    return pyjwt.encode(claims, _JWT_SECRET, algorithm=_JWT_ALGO)


def verify_jwt(token: str) -> dict:
    # Canonical swap: STETHOSCOPE_AUTH=cognito routes verification through
    # auth_cognito (JWKS, RS256) with no other code changes. Default = local.
    if os.environ.get("STETHOSCOPE_AUTH", "local").lower() == "cognito":
        from . import auth_cognito  # lazy: optional cloud path

        try:
            return auth_cognito.verify_cognito_jwt(token)
        except Exception as exc:
            raise HTTPException(status_code=401, detail=str(exc))
    try:
        return pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")


# ---- share tokens (Cloud Phase 2 — PRD 4.11 shareable links) ---------

# Share tokens are short signed JWTs carrying {trace_id, tenant_id, exp}.
# They give read-only access to one trace's data without a logged-in user.
_SHARE_TTL = 7 * 24 * 3600  # 7 days default


def issue_share_token(trace_id: str, tenant_id: str, ttl: int = _SHARE_TTL) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"share": trace_id, "tid": tenant_id, "iat": now, "exp": now + ttl},
        _JWT_SECRET, algorithm=_JWT_ALGO,
    )


def verify_share_token(token: str) -> dict:
    try:
        claims = pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="share link expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=404, detail="invalid share link")
    if "share" not in claims or "tid" not in claims:
        raise HTTPException(status_code=404, detail="invalid share link")
    return claims
