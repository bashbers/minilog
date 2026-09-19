"""limit active pumping per caregiver

Revision ID: a81f4d2c9e70
Revises: 47ccc6557a5e
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a81f4d2c9e70"
down_revision: str | None = "47ccc6557a5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The old schema allowed the same caregiver to have one active pump per Baby. Preserve every
    # record while deterministically closing older overlaps at the newest pump's start before the
    # caregiver-wide constraint is installed. Publish those edits through the normal sync feed.
    op.execute(
        """
        CREATE TEMPORARY TABLE minilog_pumping_conflicts AS
        SELECT older.id AS id,
               (SELECT MAX(newer.occurred_at_utc)
                  FROM care_records AS newer
                 WHERE newer.author_id = older.author_id
                   AND newer.record_type = 'PUMPING'
                   AND newer.ended_at_utc IS NULL
                   AND newer.deleted_at IS NULL) AS ended_at_utc
          FROM care_records AS older
         WHERE older.author_id IS NOT NULL
           AND older.record_type = 'PUMPING'
           AND older.ended_at_utc IS NULL
           AND older.deleted_at IS NULL
           AND EXISTS (
               SELECT 1
                 FROM care_records AS newer
                WHERE newer.author_id = older.author_id
                  AND newer.record_type = 'PUMPING'
                  AND newer.ended_at_utc IS NULL
                  AND newer.deleted_at IS NULL
                  AND (newer.occurred_at_utc > older.occurred_at_utc
                       OR (newer.occurred_at_utc = older.occurred_at_utc
                           AND newer.id > older.id))
           )
        """
    )
    op.execute(
        """
        UPDATE care_records
           SET ended_at_utc = (
                   SELECT MAX(care_records.occurred_at_utc, conflict.ended_at_utc)
                     FROM minilog_pumping_conflicts AS conflict
                    WHERE conflict.id = care_records.id
               ),
               updated_at = MAX(updated_at + 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000),
               revision = revision + 1
         WHERE id IN (SELECT id FROM minilog_pumping_conflicts)
        """
    )
    op.execute(
        """
        INSERT INTO sync_changes (entity_kind, entity_id, operation, revision, changed_at)
        SELECT 'care_record', record.id, 'UPSERT', record.revision, record.updated_at
          FROM care_records AS record
          JOIN minilog_pumping_conflicts AS conflict ON conflict.id = record.id
        """
    )
    op.execute("DROP TABLE minilog_pumping_conflicts")
    op.drop_index("uq_active_pumping_per_caregiver_baby", table_name="care_records")
    op.create_index(
        "uq_active_pumping_per_caregiver",
        "care_records",
        ["author_id"],
        unique=True,
        sqlite_where=sa.text(
            "record_type = 'PUMPING' AND ended_at_utc IS NULL AND deleted_at IS NULL"
        ),
    )
    op.add_column(
        "households",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("households", "revision")
    op.drop_index("uq_active_pumping_per_caregiver", table_name="care_records")
    op.create_index(
        "uq_active_pumping_per_caregiver_baby",
        "care_records",
        ["baby_id", "author_id"],
        unique=True,
        sqlite_where=sa.text(
            "record_type = 'PUMPING' AND ended_at_utc IS NULL AND deleted_at IS NULL"
        ),
    )
