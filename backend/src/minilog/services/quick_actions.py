from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from minilog.models import Caregiver, CaregiverQuickAction, RecordType
from minilog.schemas import QuickActionPreferenceOut, QuickActionPreferencesUpdate

QUICK_ACTION_TYPES = tuple(
    record_type
    for record_type in RecordType
    if record_type is not RecordType.IMPORTED_CARE_RECORD
)


def quick_actions_for(
    caregiver: Caregiver, db: Session
) -> list[QuickActionPreferenceOut]:
    stored = db.scalars(
        select(CaregiverQuickAction)
        .where(CaregiverQuickAction.caregiver_id == caregiver.id)
        .order_by(CaregiverQuickAction.position)
    ).all()
    actions = [
        QuickActionPreferenceOut(
            record_type=item.record_type,
            position=position,
            is_hidden=item.is_hidden,
        )
        for position, item in enumerate(stored)
        if item.record_type in QUICK_ACTION_TYPES
    ]
    configured = {action.record_type for action in actions}
    for record_type in QUICK_ACTION_TYPES:
        if record_type not in configured:
            actions.append(
                QuickActionPreferenceOut(
                    record_type=record_type,
                    position=len(actions),
                    is_hidden=False,
                )
            )
    return actions


def replace_quick_actions(
    caregiver: Caregiver,
    payload: QuickActionPreferencesUpdate,
    db: Session,
) -> list[QuickActionPreferenceOut]:
    db.execute(
        delete(CaregiverQuickAction).where(
            CaregiverQuickAction.caregiver_id == caregiver.id
        )
    )
    db.add_all(
        [
            CaregiverQuickAction(
                caregiver_id=caregiver.id,
                record_type=action.record_type,
                position=position,
                is_hidden=action.is_hidden,
            )
            for position, action in enumerate(payload.actions)
        ]
    )
    db.commit()
    return quick_actions_for(caregiver, db)
