# Concrete SQLite data model

This is the target relational model for the first implementation. Names are deliberately aligned with [CONTEXT.md](../CONTEXT.md). Alembic migrations are the executable source of truth once code exists.

## Storage conventions

- IDs are application-generated UUID strings stored as `TEXT` primary keys.
- Instants are UTC Unix milliseconds stored as `INTEGER`; an occurrence also stores its original local offset in minutes.
- Calendar dates are ISO `YYYY-MM-DD` strings.
- User-entered decimals are validated canonical decimal strings, avoiding binary floating-point changes in SQLite.
- Boolean values are `INTEGER NOT NULL CHECK (value IN (0, 1))`.
- Enumerations are `TEXT` with database `CHECK` constraints and matching application enums.
- Every foreign-key column is indexed. SQLite foreign keys are enabled for every connection.
- Care-record notes and text fields have explicit application and database length limits; limits catch abuse and mistakes, not medically unusual observations.

## Household and access

### `households`

| Column | Constraint |
| --- | --- |
| `id` | PK; singleton row |
| `display_name` | non-empty text |
| `time_zone` | IANA name, non-empty |
| `locale` | BCP 47 tag, initially English UI |
| `clock_format` | `12h` or `24h` |
| `measurement_system` | `metric` or `imperial` |
| `created_at`, `updated_at` | UTC milliseconds |

The application refuses creation of a second Household.

### `caregivers`

| Column | Constraint |
| --- | --- |
| `id` | PK |
| `username_normalized` | unique, non-empty |
| `username_display` | non-empty |
| `display_name` | non-empty |
| `password_hash` | Argon2id encoded hash |
| `role` | `owner` or `caregiver` |
| `is_active` | boolean |
| `created_at`, `updated_at` | UTC milliseconds |
| `identity_erased_at` | nullable UTC milliseconds |

At least one active Owner must remain. Identity erasure replaces display values and nulls historical foreign keys only after snapshot attribution has become `Deleted caregiver`.

### `invitations`

`id` PK, `token_hash` unique, `created_by_id` FK, `role` fixed to `caregiver` in the MVP, `expires_at`, `used_at`, and `created_at`. Raw tokens are never stored.

### `sessions`

`id` PK, `token_hash` unique, `caregiver_id` FK, optional user-supplied `device_name`, `created_at`, `last_seen_at`, `expires_at`, and nullable `revoked_at`. Raw session tokens are never stored.

### `caregiver_quick_actions`

Composite PK (`caregiver_id`, `record_type`), plus `position` non-negative integer and `is_hidden` boolean. A unique (`caregiver_id`, `position`) constraint applies to visible actions.

## Babies and pictures

### `babies`

`id` PK, `display_name` non-empty, `birth_date`, nullable `due_date`, `created_at`, and `updated_at`. Sex, medical identifiers, addresses, and parent details are not stored.

### `baby_profile_pictures`

`baby_id` PK/FK with cascade delete, `webp_bytes` BLOB, `width`, `height`, `content_hash`, and `updated_at`. Width equals height and the original upload is never persisted.

## Shared care-record envelope

### `care_records`

| Column | Constraint |
| --- | --- |
| `id` | PK |
| `baby_id` | FK, non-null |
| `record_type` | supported type discriminator |
| `occurred_at_utc` | UTC milliseconds |
| `local_offset_minutes` | integer from -840 through 840 |
| `ended_at_utc` | nullable; not earlier than occurrence |
| `note` | nullable plain text |
| `author_id` | nullable FK |
| `author_label` | non-empty attribution snapshot |
| `last_modified_by_id` | nullable FK |
| `last_modified_by_label` | non-empty attribution snapshot |
| `created_at`, `updated_at` | UTC milliseconds |
| `revision` | integer, starts at 1 and increases per mutation |
| `deleted_at` | nullable tombstone timestamp |
| `import_batch_id` | nullable FK |
| `import_source_line` | nullable positive integer |
| `modified_since_import` | boolean |

`record_type` is one of `breastfeeding`, `bottle_feeding`, `solid_food_feeding`, `sleep`, `diaper_change`, `pumping`, `measurement`, `medication_administration`, `note`, or `imported_care_record`. Exactly one matching detail row must exist for every non-deleted Care record; the application command creates the envelope and detail inside one transaction.

Primary timeline index: (`baby_id`, `deleted_at`, `occurred_at_utc DESC`, `id`). Active-record index: (`baby_id`, `record_type`, `ended_at_utc`) filtered to non-deleted rows with no end.

## Type-specific tables

Every `care_record_id` below is both PK and cascading FK to `care_records`.

### `breastfeeding_records`

`care_record_id` and nullable `estimated_amount_ml` non-negative integer.

### `breastfeeding_intervals`

`id` PK, `care_record_id` FK, `position` non-negative integer, `side` (`left` or `right`), `started_at_utc`, and nullable `ended_at_utc`. (`care_record_id`, `position`) is unique; interval order and non-overlap are validated. The Care record's occurrence and end bound its intervals.

### `bottle_feeding_records`

`care_record_id`, `consumed_ml` non-negative integer, nullable `offered_ml` non-negative integer, and `contents` (`breast_milk`, `formula`, `mixed`, or `other`). Offered volume, when present, cannot be below consumed volume.

### `solid_food_feeding_records`

`care_record_id`, non-empty `foods`, nullable `amount_value` canonical decimal text, nullable `amount_unit`, and nullable `reaction_note`. Amount value and unit are either both present or both absent.

### `sleep_records`

`care_record_id`. Timing is held by the common envelope.

### `diaper_change_records`

`care_record_id`, `is_wet`, `is_dirty`, nullable `stool_colour`, and nullable `stool_consistency`. At least one of wet or dirty is true; stool descriptors require dirty to be true.

### `pumping_records`

`care_record_id` and nullable `expressed_ml` non-negative integer. Timing is held by the common envelope.

### `measurement_records`

`care_record_id`, `kind` (`weight`, `height`, or `temperature`), `canonical_value`, `canonical_unit` (`kg`, `cm`, or `celsius` as dictated by kind), `entered_value`, and `entered_unit`. Canonical and entered values are canonical decimal text.

### `medication_administration_records`

`care_record_id`, non-empty `medicine_name`, positive `amount_value` canonical decimal text, nullable `unit_code`, nullable `custom_unit`, and nullable `route`. Exactly one of common unit code or custom unit is present. The unit and route registries are code-defined.

### `note_records`

`care_record_id` and non-empty `body` plain text.

### `imported_care_records`

`care_record_id`, non-empty `raw_label`, nullable `raw_details`, and non-empty `raw_line`. These records reject normal update commands.

## Active-record constraints

Partial unique indexes enforce:

- One active sleep per Baby.
- One active breastfeeding record per Baby.
- One active pumping record per (`baby_id`, `author_id`) so each Caregiver may run one for the selected Baby.

An active record is non-deleted with `ended_at_utc IS NULL`. Application validation supplies a readable domain conflict when an index rejects a race.

## PiyoLog imports

### `import_batches`

`id` PK, `baby_id` FK, `created_by_id` FK, `original_filename`, unique `source_hash`, `source_time_zone`, `detected_locale`, `detected_platform`, `format`, `date_from`, `date_to`, `status`, `report_json`, `source_contents` nullable BLOB, `created_at`, and nullable `source_deleted_at`.

The report is diagnostic import metadata rather than a user-defined care schema, so JSON is appropriate here. Confirmed domain records remain fully relational.

### `imported_daily_notes`

`id` PK, `baby_id` FK, `local_date`, `body`, nullable `source_author_text`, `import_batch_id` FK, nullable `source_line`, and `created_at`. These notes are read-only and sort with their date without an invented occurrence time.

Recognized Care records reference their Import batch through `care_records.import_batch_id`. Deleting retained `source_contents` leaves the batch, report, provenance, and resulting records intact.

## Synchronization

### `sync_changes`

`sequence` integer autoincrement PK, `entity_kind`, `entity_id`, `operation` (`upsert` or `delete`), `revision`, and `changed_at`. A domain mutation and its change row commit atomically.

### `processed_mutations`

`mutation_id` UUID-text PK, `caregiver_id` FK, `entity_kind`, `entity_id`, `result_revision`, `processed_at`, and a bounded replay result. This makes retries return the original semantic result.

### `sync_state`

Singleton row containing `oldest_valid_sequence` and `last_pruned_at`. Changes and processed mutations remain available for at least 30 days. Pruning advances the cursor floor transactionally.

## Deletion behaviour

Care-record deletion first creates a tombstone so active devices can synchronize. After the synchronization horizon, maintenance may physically remove its detail and envelope rows. Baby and Household permanent deletion bypass ordinary retention after typed Owner confirmation and cascade through all application-owned rows.

Profile-picture replacement immediately deletes the old BLOB. Erasing a Caregiver identity preserves Care records and replaces attribution with `Deleted caregiver`.
