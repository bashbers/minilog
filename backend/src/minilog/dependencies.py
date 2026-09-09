from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from minilog.database import get_db
from minilog.models import AuthSession, Caregiver, CaregiverRole, now_ms
from minilog.security import CSRF_COOKIE, SESSION_COOKIE, find_session, hash_token

Database = Annotated[Session, Depends(get_db)]


async def get_auth_session(
    db: Database,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> AuthSession:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication_required"
        )
    auth_session = find_session(db, session_token)
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    auth_session.last_seen_at = now_ms()
    return auth_session


AuthSessionDep = Annotated[AuthSession, Depends(get_auth_session)]


async def get_current_caregiver(auth_session: AuthSessionDep) -> Caregiver:
    return auth_session.caregiver


CurrentCaregiver = Annotated[Caregiver, Depends(get_current_caregiver)]


async def require_owner(caregiver: CurrentCaregiver) -> Caregiver:
    if caregiver.role is not CaregiverRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner_required")
    return caregiver


Owner = Annotated[Caregiver, Depends(require_owner)]


async def require_csrf(
    request: Request,
    auth_session: AuthSessionDep,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if not csrf_header or not csrf_cookie or csrf_header != csrf_cookie:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf_failed")
    if hash_token(csrf_header) != auth_session.csrf_token_hash:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf_failed")


CsrfProtected = Annotated[None, Depends(require_csrf)]
