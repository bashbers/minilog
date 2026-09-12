import hashlib
import hmac
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from minilog.config import Settings
from minilog.models import AuthSession, Caregiver, now_ms

SESSION_COOKIE = "minilog_session"
CSRF_COOKIE = "minilog_csrf"

password_hasher = PasswordHasher()


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def is_password_hash(encoded: str) -> bool:
    try:
        password_hasher.check_needs_rehash(encoded)
        return True
    except InvalidHashError:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(provided: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(provided, expected)


def create_session(
    db: Session, caregiver: Caregiver, settings: Settings, device_name: str | None = None
) -> tuple[AuthSession, str, str]:
    session_token = new_token()
    csrf_token = new_token()
    expires_at = now_ms() + int(timedelta(days=settings.session_days).total_seconds() * 1000)
    auth_session = AuthSession(
        token_hash=hash_token(session_token),
        csrf_token_hash=hash_token(csrf_token),
        caregiver_id=caregiver.id,
        device_name=device_name,
        expires_at=expires_at,
    )
    db.add(auth_session)
    db.flush()
    return auth_session, session_token, csrf_token


def find_session(db: Session, raw_token: str) -> AuthSession | None:
    auth_session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token))
    )
    if auth_session is None or auth_session.revoked_at is not None:
        return None
    if auth_session.expires_at <= now_ms() or not auth_session.caregiver.is_active:
        return None
    return auth_session
