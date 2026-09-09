from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
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
    response: Response,
    db: Database,
    settings: SettingsDep,
) -> SessionOut:
    caregiver = db.scalar(
        select(Caregiver).where(
            Caregiver.username_normalized == normalize_username(payload.username),
            Caregiver.is_active.is_(True),
        )
    )
    if caregiver is None or not verify_password(caregiver.password_hash, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

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
