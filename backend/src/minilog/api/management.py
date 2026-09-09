from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from minilog.api.auth import session_response, set_session_cookies
from minilog.config import get_settings
from minilog.dependencies import (
    AuthSessionDep,
    CsrfProtected,
    CurrentCaregiver,
    Database,
    Owner,
)
from minilog.models import AuthSession, Caregiver, CaregiverRole, Invitation, now_ms
from minilog.schemas import (
    CaregiverOut,
    DeviceSessionOut,
    InvitationAccept,
    InvitationCreate,
    InvitationOut,
    PasswordChange,
    SessionOut,
)
from minilog.security import (
    create_session,
    hash_password,
    hash_token,
    new_token,
    normalize_username,
    verify_password,
)

router = APIRouter(tags=["caregivers and devices"])


@router.post("/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: InvitationCreate,
    owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
) -> InvitationOut:
    settings = get_settings()
    token = new_token()
    hours = payload.expires_in_hours or settings.invitation_hours
    invitation = Invitation(
        token_hash=hash_token(token),
        created_by_id=owner.id,
        role=CaregiverRole.CAREGIVER,
        expires_at=now_ms() + int(timedelta(hours=hours).total_seconds() * 1000),
    )
    db.add(invitation)
    db.commit()
    return InvitationOut(id=invitation.id, token=token, expires_at=invitation.expires_at)


@router.post("/invitations/accept", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def accept_invitation(
    payload: InvitationAccept,
    response: Response,
    db: Database,
) -> SessionOut:
    invitation = db.scalar(
        select(Invitation).where(Invitation.token_hash == hash_token(payload.token))
    )
    if invitation is None or invitation.used_at is not None or invitation.expires_at <= now_ms():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="invitation_unavailable")
    normalized = normalize_username(payload.username)
    if db.scalar(select(Caregiver.id).where(Caregiver.username_normalized == normalized)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username_unavailable")

    caregiver = Caregiver(
        username_normalized=normalized,
        username_display=payload.username.strip(),
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        role=invitation.role,
    )
    db.add(caregiver)
    db.flush()
    invitation.used_at = now_ms()
    settings = get_settings()
    auth_session, session_token, csrf_token = create_session(
        db, caregiver, settings, payload.device_name
    )
    db.commit()
    set_session_cookies(response, session_token, csrf_token, settings)
    return session_response(caregiver, csrf_token, auth_session.expires_at)


@router.get("/caregivers", response_model=list[CaregiverOut])
async def list_caregivers(_owner: Owner, db: Database) -> list[CaregiverOut]:
    caregivers = db.scalars(
        select(Caregiver).where(Caregiver.is_active.is_(True)).order_by(Caregiver.created_at)
    ).all()
    return [CaregiverOut.model_validate(item) for item in caregivers]


@router.delete("/caregivers/{caregiver_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_caregiver(
    caregiver_id: UUID,
    owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
) -> Response:
    caregiver = db.get(Caregiver, str(caregiver_id))
    if caregiver is None or not caregiver.is_active:
        raise HTTPException(status_code=404, detail="caregiver_not_found")
    if caregiver.id == owner.id:
        raise HTTPException(status_code=409, detail="cannot_remove_current_owner")
    caregiver.is_active = False
    caregiver.updated_at = now_ms()
    for auth_session in db.scalars(
        select(AuthSession).where(
            AuthSession.caregiver_id == caregiver.id,
            AuthSession.revoked_at.is_(None),
        )
    ):
        auth_session.revoked_at = now_ms()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/devices", response_model=list[DeviceSessionOut])
async def list_device_sessions(
    auth_session: AuthSessionDep,
    _caregiver: CurrentCaregiver,
    db: Database,
) -> list[DeviceSessionOut]:
    sessions = db.scalars(
        select(AuthSession)
        .where(
            AuthSession.caregiver_id == auth_session.caregiver_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now_ms(),
        )
        .order_by(AuthSession.last_seen_at.desc())
    ).all()
    return [
        DeviceSessionOut(
            id=item.id,
            device_name=item.device_name,
            created_at=item.created_at,
            last_seen_at=item.last_seen_at,
            expires_at=item.expires_at,
            current=item.id == auth_session.id,
        )
        for item in sessions
    ]


@router.delete("/sessions/devices/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device_session(
    session_id: UUID,
    auth_session: AuthSessionDep,
    _csrf: CsrfProtected,
    db: Database,
) -> Response:
    target = db.get(AuthSession, str(session_id))
    if target is None or target.caregiver_id != auth_session.caregiver_id:
        raise HTTPException(status_code=404, detail="session_not_found")
    target.revoked_at = now_ms()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/sessions/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange,
    auth_session: AuthSessionDep,
    caregiver: CurrentCaregiver,
    _csrf: CsrfProtected,
    db: Database,
) -> Response:
    if not verify_password(caregiver.password_hash, payload.current_password):
        raise HTTPException(status_code=403, detail="current_password_incorrect")
    caregiver.password_hash = hash_password(payload.new_password)
    caregiver.updated_at = now_ms()
    for other in db.scalars(
        select(AuthSession).where(
            AuthSession.caregiver_id == caregiver.id,
            AuthSession.id != auth_session.id,
            AuthSession.revoked_at.is_(None),
        )
    ):
        other.revoked_at = now_ms()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
