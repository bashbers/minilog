import hashlib
import io
import warnings
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from minilog.config import get_settings
from minilog.database import private_database_changes
from minilog.dependencies import CsrfProtected, CurrentCaregiver, Database, Owner
from minilog.models import (
    Baby,
    BabyProfilePicture,
    now_ms,
)
from minilog.schemas import BabyCreate, BabyDeleteRequest, BabyOut, BabyUpdate
from minilog.services.destructive import (
    BabyNotFoundError,
    ConfirmationMismatchError,
    ExportAcknowledgementRequiredError,
    permanently_delete_baby,
)

router = APIRouter(tags=["babies"])


def baby_out(baby: Baby) -> BabyOut:
    return BabyOut(
        id=baby.id,
        display_name=baby.display_name,
        birth_date=baby.birth_date,
        due_date=baby.due_date,
        has_profile_picture=baby.profile_picture is not None,
        updated_at=baby.updated_at,
    )


@router.get("/babies", response_model=list[BabyOut])
async def list_babies(_caregiver: CurrentCaregiver, db: Database) -> list[BabyOut]:
    babies = db.scalars(select(Baby).order_by(Baby.created_at, Baby.id)).all()
    return [baby_out(baby) for baby in babies]


@router.post("/babies", response_model=BabyOut, status_code=status.HTTP_201_CREATED)
async def create_baby(
    payload: BabyCreate, _owner: Owner, _csrf: CsrfProtected, db: Database
) -> BabyOut:
    baby = Baby(
        display_name=payload.display_name.strip(),
        birth_date=payload.birth_date.isoformat(),
        due_date=payload.due_date.isoformat() if payload.due_date else None,
    )
    db.add(baby)
    db.commit()
    db.refresh(baby)
    return baby_out(baby)


@router.put("/babies/{baby_id}", response_model=BabyOut)
async def update_baby(
    baby_id: str,
    payload: BabyUpdate,
    _owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
) -> BabyOut:
    baby = db.get(Baby, baby_id)
    if baby is None:
        raise HTTPException(status_code=404, detail="baby_not_found")
    baby.display_name = payload.display_name.strip()
    baby.birth_date = payload.birth_date.isoformat()
    baby.due_date = payload.due_date.isoformat() if payload.due_date else None
    baby.updated_at = max(now_ms(), baby.updated_at + 1)
    db.commit()
    db.refresh(baby)
    return baby_out(baby)


@router.put("/babies/{baby_id}/profile-picture", status_code=status.HTTP_204_NO_CONTENT)
async def set_profile_picture(
    baby_id: str,
    _caregiver: CurrentCaregiver,
    _csrf: CsrfProtected,
    db: Database,
    image: Annotated[UploadFile, File()],
) -> None:
    settings = get_settings()
    raw = await image.read(settings.max_profile_picture_bytes + 1)
    if len(raw) > settings.max_profile_picture_bytes:
        raise HTTPException(status_code=413, detail="profile_picture_too_large")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(status_code=415, detail="unsupported_picture_type")
                if source.width * source.height > settings.max_profile_picture_pixels:
                    raise HTTPException(
                        status_code=413, detail="profile_picture_dimensions_too_large"
                    )
                source.load()
                oriented = ImageOps.exif_transpose(source).convert("RGB")
                size = min(oriented.size)
                left = (oriented.width - size) // 2
                top = (oriented.height - size) // 2
                square = oriented.crop((left, top, left + size, top + size)).resize((256, 256))
                output = io.BytesIO()
                square.save(output, format="WEBP", quality=85, method=6)
                derivative = output.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(
            status_code=413, detail="profile_picture_dimensions_too_large"
        ) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=415, detail="invalid_profile_picture") from exc

    with private_database_changes(db):
        baby = db.get(Baby, baby_id)
        if baby is None:
            raise HTTPException(status_code=404, detail="baby_not_found")
        changed_at = max(now_ms(), baby.updated_at + 1)
        picture = db.get(BabyProfilePicture, baby_id)
        if picture is None:
            picture = BabyProfilePicture(
                baby_id=baby_id,
                webp_bytes=derivative,
                width=256,
                height=256,
                content_hash=hashlib.sha256(derivative).hexdigest(),
                updated_at=changed_at,
            )
            db.add(picture)
        else:
            picture.webp_bytes = derivative
            picture.content_hash = hashlib.sha256(derivative).hexdigest()
            picture.updated_at = changed_at
        baby.updated_at = changed_at


@router.get("/babies/{baby_id}/profile-picture")
async def get_profile_picture(baby_id: str, _caregiver: CurrentCaregiver, db: Database) -> Response:
    picture = db.get(BabyProfilePicture, baby_id)
    if picture is None:
        raise HTTPException(status_code=404, detail="profile_picture_not_found")
    return Response(
        picture.webp_bytes,
        media_type="image/webp",
        headers={"ETag": f'"{picture.content_hash}"', "Cache-Control": "private, no-store"},
    )


@router.delete("/babies/{baby_id}/profile-picture", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile_picture(
    baby_id: str,
    _caregiver: CurrentCaregiver,
    _csrf: CsrfProtected,
    db: Database,
) -> None:
    with private_database_changes(db):
        baby = db.get(Baby, baby_id)
        if baby is None:
            raise HTTPException(status_code=404, detail="baby_not_found")
        picture = db.get(BabyProfilePicture, baby_id)
        if picture is not None:
            baby.updated_at = max(now_ms(), baby.updated_at + 1)
            db.delete(picture)


@router.delete("/babies/{baby_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_baby(
    baby_id: str,
    payload: BabyDeleteRequest,
    _owner: Owner,
    _csrf: CsrfProtected,
    db: Database,
) -> Response:
    try:
        permanently_delete_baby(
            db,
            baby_id,
            payload.confirmation,
            payload.export_acknowledged,
        )
    except BabyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="baby_not_found") from exc
    except ExportAcknowledgementRequiredError as exc:
        raise HTTPException(status_code=409, detail="export_acknowledgement_required") from exc
    except ConfirmationMismatchError as exc:
        raise HTTPException(status_code=409, detail="confirmation_did_not_match") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
