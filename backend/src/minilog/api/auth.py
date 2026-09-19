import json
import logging
from collections import defaultdict, deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select

from minilog.config import Settings, get_settings_dependency
from minilog.database import SessionLocal
from minilog.dependencies import AuthSessionDep, CsrfProtected, CurrentCaregiver, Database
from minilog.models import Caregiver, CaregiverRole, Household, now_ms
from minilog.schemas import (
    CaregiverOut,
    LoginRequest,
    SessionOut,
    SetupRequest,
    SetupStatus,
)
from minilog.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    create_session,
    hash_password,
    normalize_username,
    token_matches,
    verify_password,
)

router = APIRouter(tags=["authentication"])
SettingsDep = Annotated[Settings, Depends(get_settings_dependency)]
logger = logging.getLogger("minilog.security")
_failed_logins: dict[tuple[str, str], deque[int]] = defaultdict(deque)
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$JFm8qSu2guXf6SRzIJlLig$"
    "jl7KjHlkOgNMmaEutUPd8NAQvjdsLzpio6prONHaMig"
)


def login_rate_keys(request: Request, username: str) -> tuple[tuple[str, str], tuple[str, str]]:
    client = request.headers.get("X-Minilog-Client-IP") or (
        request.client.host if request.client else "unknown"
    )
    return ("source", client), ("username", normalize_username(username))


def enforce_login_rate_limit(keys: tuple[tuple[str, str], ...], settings: Settings) -> None:
    cutoff = now_ms() - settings.login_attempt_window_seconds * 1000
    for key in keys:
        attempts = _failed_logins[key]
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= settings.login_attempt_limit:
            logger.warning(
                json.dumps(
                    {
                        "event": "authentication_rate_limited",
                        "limit_dimension": key[0],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="try_again_later",
            )


def set_session_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
    settings: Settings,
) -> None:
    max_age = settings.session_days * 24 * 60 * 60
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=max_age,
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        secure=settings.secure_cookies,
        httponly=False,
        samesite="lax",
        path="/",
    )


def session_response(caregiver: Caregiver, csrf_token: str, expires_at: int) -> SessionOut:
    return SessionOut(
        caregiver=CaregiverOut.model_validate(caregiver),
        csrf_token=csrf_token,
        expires_at=expires_at,
    )


@router.get("/setup", response_model=SetupStatus)
async def setup_status() -> SetupStatus:
    with SessionLocal() as db:
        owner_count = db.scalar(
            select(func.count()).select_from(Caregiver).where(Caregiver.role == CaregiverRole.OWNER)
        )
    return SetupStatus(setup_required=owner_count == 0)


@router.post("/setup", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def setup(
    payload: SetupRequest,
    response: Response,
    db: Database,
    settings: SettingsDep,
) -> SessionOut:
    owner_count = db.scalar(
        select(func.count()).select_from(Caregiver).where(Caregiver.role == CaregiverRole.OWNER)
    )
    if owner_count:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="setup_already_complete")
    if not token_matches(payload.setup_token, settings.setup_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_setup_token")
    if db.scalar(select(func.count()).select_from(Household)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="household_already_exists")

    household = Household(
        display_name=payload.household_name.strip(),
        time_zone=payload.time_zone,
    )
    caregiver = Caregiver(
        username_normalized=normalize_username(payload.username),
        username_display=payload.username.strip(),
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        role=CaregiverRole.OWNER,
    )
    db.add_all([household, caregiver])
    db.flush()
    auth_session, session_token, csrf_token = create_session(db, caregiver, settings, "Setup")
    db.commit()
    set_session_cookies(response, session_token, csrf_token, settings)
    return session_response(caregiver, csrf_token, auth_session.expires_at)


@router.post("/sessions", response_model=SessionOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Database,
    settings: SettingsDep,
) -> SessionOut:
    rate_keys = login_rate_keys(request, payload.username)
    enforce_login_rate_limit(rate_keys, settings)
    caregiver = db.scalar(
        select(Caregiver).where(
            Caregiver.username_normalized == normalize_username(payload.username),
            Caregiver.is_active.is_(True),
        )
    )
    password_matches = verify_password(
        caregiver.password_hash if caregiver is not None else DUMMY_PASSWORD_HASH,
        payload.password,
    )
    if caregiver is None or not password_matches:
        failed_at = now_ms()
        for key in rate_keys:
            _failed_logins[key].append(failed_at)
        logger.warning('{"event":"authentication_failed","reason":"invalid_credentials"}')
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    # A valid account proves only that username. Source failures must age out naturally so an
    # attacker cannot use one known credential to reset protection for password spraying.
    _failed_logins.pop(rate_keys[1], None)
    auth_session, session_token, csrf_token = create_session(
        db, caregiver, settings, payload.device_name
    )
    db.commit()
    set_session_cookies(response, session_token, csrf_token, settings)
    return session_response(caregiver, csrf_token, auth_session.expires_at)


@router.get("/sessions/current", response_model=CaregiverOut)
async def current_session(caregiver: CurrentCaregiver, db: Database) -> CaregiverOut:
    db.commit()
    return CaregiverOut.model_validate(caregiver)


@router.delete("/sessions/current", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    auth_session: AuthSessionDep,
    _csrf: CsrfProtected,
    db: Database,
) -> None:
    auth_session.revoked_at = now_ms()
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
