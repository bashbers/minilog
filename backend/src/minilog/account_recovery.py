import argparse
import getpass

from sqlalchemy import select

from minilog.database import SessionLocal
from minilog.models import AuthSession, Caregiver, CaregiverRole, now_ms
from minilog.security import hash_password


def reset_owner_password(password: str) -> None:
    with SessionLocal() as db:
        owner = db.scalar(
            select(Caregiver).where(
                Caregiver.role == CaregiverRole.OWNER,
                Caregiver.is_active.is_(True),
            )
        )
        if owner is None:
            raise RuntimeError("No active Owner exists.")
        owner.password_hash = hash_password(password)
        owner.updated_at = now_ms()
        for auth_session in db.scalars(
            select(AuthSession).where(
                AuthSession.caregiver_id == owner.id,
                AuthSession.revoked_at.is_(None),
            )
        ):
            auth_session.revoked_at = now_ms()
        db.commit()


def reset_owner_main() -> None:
    parser = argparse.ArgumentParser(description="Reset the local Minilog Owner password.")
    parser.parse_args()
    first = getpass.getpass("New Owner password (minimum 12 characters): ")
    second = getpass.getpass("Repeat new Owner password: ")
    if first != second:
        raise SystemExit("Passwords did not match.")
    if len(first) < 12:
        raise SystemExit("Password must be at least 12 characters.")
    try:
        reset_owner_password(first)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print("Owner password reset; all existing sessions were revoked.")
