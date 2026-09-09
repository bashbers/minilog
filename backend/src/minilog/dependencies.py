from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from minilog.config import get_settings
from minilog.database import get_db
from minilog.models import AuthSession, Caregiver, CaregiverRole, now_ms
from minilog.security import CSRF_COOKIE, SESSION_COOKIE, find_session, hash_token

Database = Annotated[Session, Depends(get_db)]


async def get_auth_session(
    db: Database,
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    csrf_token: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
) -> AuthSession:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication_required"
        )
    auth_session = find_session(db, session_token)
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    current_time = now_ms()
    if current_time - auth_session.last_seen_at >= 12 * 60 * 60 * 1000:
        settings = get_settings()
        max_age = settings.session_days * 24 * 60 * 60
        auth_session.last_seen_at = current_time
        auth_session.expires_at = current_time + max_age * 1000
        db.commit()
        response.set_cookie(
            SESSION_COOKIE,
            session_token,
            max_age=max_age,
            secure=settings.secure_cookies,
            httponly=True,
            samesite="lax",
            path="/",
        )
        if csrf_token:
            response.set_cookie(
                CSRF_COOKIE,
                csrf_token,
                max_age=max_age,
                secure=settings.secure_cookies,
                httponly=False,
                samesite="lax",
                path="/",
            )
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
