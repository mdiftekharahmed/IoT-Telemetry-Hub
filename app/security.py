import hashlib
import secrets
from datetime import timedelta

from pwdlib import PasswordHash
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import AdminSession, utcnow

password_hasher = PasswordHash.recommended()
# A dummy hash keeps unknown-user login work comparable to a wrong password.
DUMMY_HASH = password_hasher.hash("not-a-real-admin-password")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, username: str, ttl_hours: int) -> str:
    db.execute(delete(AdminSession).where(AdminSession.expires_at <= utcnow()))
    token = secrets.token_urlsafe(32)
    db.add(
        AdminSession(
            token_hash=token_digest(token),
            username=username,
            expires_at=utcnow() + timedelta(hours=ttl_hours),
        )
    )
    db.commit()
    return token
