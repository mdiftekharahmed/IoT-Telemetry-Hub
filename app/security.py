"""Auth, HMAC, and RBAC helpers for ColdChain."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pwdlib import PasswordHash
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import AdminSession, User, utcnow

# ── Legacy session auth (kept for old admin SPA) ──────────────────────────────
password_hasher = PasswordHash.recommended()
DUMMY_HASH = password_hasher.hash("not-a-real-admin-password")

bearer = HTTPBearer(auto_error=False)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, username: str, ttl_hours: int) -> str:
    db.execute(delete(AdminSession).where(AdminSession.expires_at <= utcnow()))
    token = secrets.token_urlsafe(32)
    db.add(AdminSession(
        token_hash=token_digest(token),
        username=username,
        expires_at=utcnow() + timedelta(hours=ttl_hours),
    ))
    db.commit()
    return token


# ── JWT auth (ColdChain role-based) ───────────────────────────────────────────
ALGORITHM = "HS256"
ACCESS_TTL_MIN = 30
REFRESH_TTL_DAYS = 7


def _get_secret(request: Request) -> str:
    return request.app.state.settings.coldchain_jwt_secret


def create_tokens(user: User, secret: str) -> dict:
    now = utcnow()
    access_payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "type": "access",
        "iat": now.timestamp(),
        "exp": (now + timedelta(minutes=ACCESS_TTL_MIN)).timestamp(),
    }
    refresh_payload = {
        "sub": str(user.id),
        "type": "refresh",
        "iat": now.timestamp(),
        "exp": (now + timedelta(days=REFRESH_TTL_DAYS)).timestamp(),
    }
    return {
        "access_token":  jwt.encode(access_payload, secret, algorithm=ALGORITHM),
        "refresh_token": jwt.encode(refresh_payload, secret, algorithm=ALGORITHM),
        "token_type":    "bearer",
        "expires_in":    ACCESS_TTL_MIN * 60,
    }


def decode_access_token(token: str, secret: str) -> dict:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise JWTError("not an access token")
        return payload
    except JWTError as e:
        raise HTTPException(401, f"Invalid token: {e}") from e


def decode_refresh_token(token: str, secret: str) -> dict:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise JWTError("not a refresh token")
        return payload
    except JWTError as e:
        raise HTTPException(401, f"Invalid refresh token: {e}") from e


# ── RBAC dependency factory ────────────────────────────────────────────────────

def require_role(*roles: str):
    """FastAPI dependency: bearer JWT must carry one of the listed roles."""
    from app.db import session_factory  # avoid circular import

    async def check(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> User:
        if not credentials:
            raise HTTPException(401, "Bearer token required")
        secret = _get_secret(request)
        payload = decode_access_token(credentials.credentials, secret)
        if payload["role"] not in roles:
            raise HTTPException(403, f"Role '{payload['role']}' is not allowed here")
        # Fetch live user to check active flag
        with request.app.state.sessions() as db:
            user = db.get(User, int(payload["sub"]))
        if not user or not user.active:
            raise HTTPException(403, "Account inactive")
        return user

    return check


# Role alias dependencies (import these in api.py)
AnyRole   = require_role("admin", "pharmacist", "inspector")
AdminOnly = require_role("admin")
PharmOrAdmin = require_role("admin", "pharmacist")


# ── HMAC device message signing ───────────────────────────────────────────────

def canonical_json(d: dict) -> str:
    """Deterministic JSON: sorted keys, no extra spaces, 2-dp floats."""
    def _default(obj):
        if isinstance(obj, float):
            return f"{obj:.2f}"
        raise TypeError(type(obj))
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=_default)


def hmac_sign(secret_hex: str, parts: list[str]) -> str:
    """Return lowercase hex HMAC-SHA256 over '|'.join(parts)."""
    key   = bytes.fromhex(secret_hex)
    msg   = "|".join(str(p) for p in parts).encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def hmac_verify(secret_hex: str, parts: list[str], provided_sig: str) -> bool:
    """Constant-time HMAC comparison."""
    expected = hmac_sign(secret_hex, parts)
    return hmac.compare_digest(expected, provided_sig.lower())
