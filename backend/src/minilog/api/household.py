from fastapi import APIRouter
from sqlalchemy import select

from minilog.dependencies import CurrentCaregiver, Database
from minilog.models import Household
from minilog.schemas import HouseholdOut

router = APIRouter(tags=["household"])


@router.get("/household", response_model=HouseholdOut)
async def get_household(_caregiver: CurrentCaregiver, db: Database) -> HouseholdOut:
    household = db.scalar(select(Household))
    if household is None:
        raise RuntimeError("configured Household is missing")
    return HouseholdOut.model_validate(household)
