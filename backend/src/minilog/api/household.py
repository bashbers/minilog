from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, select

from minilog.dependencies import CsrfProtected, CurrentCaregiver, Database, Owner
from minilog.models import (
    AuthSession,
    Baby,
    Caregiver,
    CaregiverQuickAction,
    CareRecord,
    Household,
    ImportBatch,
    ImportedDailyNote,
    Invitation,
    ProcessedMutation,
    SyncChange,
    SyncState,
)
from minilog.schemas import HouseholdDeleteRequest, HouseholdOut
from minilog.security import CSRF_COOKIE, SESSION_COOKIE

router = APIRouter(tags=["household"])


@router.get("/household", response_model=HouseholdOut)
async def get_household(_caregiver: CurrentCaregiver, db: Database) -> HouseholdOut:
    household = db.scalar(select(Household))
    if household is None:
        raise RuntimeError("configured Household is missing")
    return HouseholdOut.model_validate(household)


@router.delete("/household", status_code=status.HTTP_204_NO_CONTENT)
async def delete_household(
    payload: HouseholdDeleteRequest,
    response: Response,
    _owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
) -> None:
    household = db.scalar(select(Household))
    if household is None:
        raise HTTPException(status_code=404, detail="household_not_found")
    if payload.confirmation != f"DELETE {household.display_name}":
        raise HTTPException(status_code=409, detail="confirmation_did_not_match")

    for model in (
        ProcessedMutation,
        SyncChange,
        SyncState,
        ImportedDailyNote,
        CareRecord,
        ImportBatch,
        Baby,
        Invitation,
        AuthSession,
        CaregiverQuickAction,
        Caregiver,
        Household,
    ):
        db.execute(delete(model))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
