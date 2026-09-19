from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from minilog.dependencies import CsrfProtected, CurrentCaregiver, Database, Owner
from minilog.models import Household, now_ms
from minilog.schemas import (
    HouseholdConflictResponse,
    HouseholdDeleteRequest,
    HouseholdOut,
    HouseholdStaleRevisionDetail,
    HouseholdUpdate,
)
from minilog.security import CSRF_COOKIE, SESSION_COOKIE
from minilog.services.destructive import (
    ConfirmationMismatchError,
    HouseholdNotFoundError,
    permanently_delete_household,
)

router = APIRouter(tags=["household"])


@router.get("/household", response_model=HouseholdOut)
async def get_household(_caregiver: CurrentCaregiver, db: Database) -> HouseholdOut:
    household = db.scalar(select(Household))
    if household is None:
        raise RuntimeError("configured Household is missing")
    return HouseholdOut.model_validate(household)


@router.put(
    "/household",
    response_model=HouseholdOut,
    responses={409: {"model": HouseholdConflictResponse}},
)
async def update_household(
    payload: HouseholdUpdate,
    _owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
) -> HouseholdOut:
    household = db.scalar(select(Household))
    if household is None:
        raise HTTPException(status_code=404, detail="household_not_found")
    if household.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail=HouseholdStaleRevisionDetail(
                current=HouseholdOut.model_validate(household)
            ).model_dump(mode="json"),
        )
    household.display_name = payload.display_name.strip()
    household.time_zone = payload.time_zone.strip()
    household.locale = payload.locale.strip()
    household.clock_format = payload.clock_format
    household.measurement_system = payload.measurement_system
    household.updated_at = max(now_ms(), household.updated_at + 1)
    household.revision += 1
    db.commit()
    db.refresh(household)
    return HouseholdOut.model_validate(household)


@router.delete("/household", status_code=status.HTTP_204_NO_CONTENT)
async def delete_household(
    payload: HouseholdDeleteRequest,
    response: Response,
    _owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
) -> None:
    try:
        permanently_delete_household(db, payload.confirmation)
    except HouseholdNotFoundError as exc:
        raise HTTPException(status_code=404, detail="household_not_found") from exc
    except ConfirmationMismatchError as exc:
        raise HTTPException(status_code=409, detail="confirmation_did_not_match") from exc
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
