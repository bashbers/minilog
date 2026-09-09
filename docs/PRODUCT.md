# Minilog product contract

## Purpose

Minilog gives a household a fast, shared account of a baby's day without advertising, tracking, vendor hosting, or third-party runtime requests. Its primary outcome is reliable caregiver handover. Daily and longer-term summaries help caregivers observe routines, but Minilog does not interpret health or development.

## Product principles

1. Baby and caregiver data stays inside the household's self-hosted deployment.
2. Logging a care occurrence must be quick enough to do one-handed and while tired.
3. A caregiver must always be able to tell which Baby is selected before recording.
4. Creation remains available during a temporary outage; ambiguous edits never silently win.
5. Users can leave with a complete, documented export.
6. Minilog records observations. It does not diagnose, prescribe, judge, or make safety-critical promises.

## Audience and operating boundary

- One Household per deployment.
- Technically capable self-hosters are the initial operators.
- A Household may contain multiple Babies, one Owner, and multiple Caregivers.
- The MVP supports one-Baby-at-a-time workflows. Each baby-level record belongs to exactly one Baby, with no bulk or "repeat for another baby" action.
- Local-network exposure is the Compose default. Remote operators provide an HTTPS reverse proxy or private VPN.
- Managed hosting, multi-tenant operation, and horizontal application scaling are not supported.

## Roles

| Capability | Owner | Caregiver |
| --- | ---: | ---: |
| View, create, edit, and delete care records | Yes | Yes |
| Start and stop timed records | Yes | Yes |
| Change a Baby's profile picture | Yes | Yes |
| Manage own quick-action preferences | Yes | Yes |
| Manage Baby identity details | Yes | No |
| Invite, deactivate, or erase Caregivers | Yes | No |
| Import and export Household data | Yes | No |
| Change Household settings | Yes | No |
| Permanently delete a Baby or Household | Yes | No |

Removed Caregivers lose access immediately. Historical attribution remains unless the Owner erases that identity, after which records say `Deleted caregiver`.

## MVP care records

All Care records have a Baby, type, occurrence time, original local offset, author, optional note, creation and modification times, and revision. Timed records have a start and optional end. Different timed types may overlap.

| Type | MVP detail |
| --- | --- |
| Breastfeeding | Ordered left/right intervals, totals by side, optional estimated amount; one active record per Baby |
| Bottle feeding | Consumed volume, optional offered volume, and breast milk/formula/mixed/other contents |
| Solid-food feeding | Free-text foods, optional amount and unit, optional observed-reaction note |
| Sleep | Start and optional end; one active record per Baby |
| Diaper change | Wet, dirty, or both; optional stool colour, consistency, and note |
| Pumping | Start, optional end, and optional expressed volume; attached to the selected Baby and one active record per Caregiver |
| Measurement | Weight, height, or temperature, preserving canonical and originally entered values and units |
| Medication administration | Medicine name, decimal amount, common or custom unit, optional route, and note |
| Note | Plain text with line breaks; no markup, active links, or attachments |
| Imported care record | Read-only preservation of an unrecognized PiyoLog line |

Medication records document administrations only. Prescriptions, dose guidance, schedules, reminders, inventory, and medical warnings are outside the MVP.

## Primary experience

### Today

Minilog opens on Today for the selected Baby. The top of the screen makes selection unmistakable with display name and optional profile picture. The page shows active timed records, a chronological list, and daily totals.

The interface is mobile-first and dark-first: dark mode is the design baseline and must remain clearly legible in daylight. It uses strong contrast, large touch targets, and bottom-reachable, one-handed quick actions. Colour is never the sole status cue. The MVP also meets keyboard and screen-reader needs and respects reduced motion.

### Navigation

Bottom navigation contains Today, History, and Trends. A prominent quick-add action opens a bottom sheet whose actions each Caregiver may hide and reorder. Cross-Baby active-record indicators remain visible when the selected Baby changes.

### History

History is paginated and filterable by date range and care type. Full-text search and saved filters are deferred. Imported daily notes appear with their calendar date without an invented timestamp.

### Trends

Daily totals and 7-day and 30-day views cover feeding, sleep, diapers, pumping, and measurements. Charts show entered facts and raw trends only. They contain no percentiles, thresholds, predictions, or normal/abnormal labels.

## Offline and shared updates

- New care records may be created offline and are queued on the device.
- Existing records require connectivity to edit or delete.
- An open, visible app polls incremental changes every five seconds and also syncs at launch, reconnection, and foreground return.
- Changes merge by stable identifier and revision. A stale edit produces a visible conflict instead of overwriting newer data.
- The browser caches only the selected Baby's recent seven days, the current profile picture, and pending writes.
- Logout clears local Household data.

## Profile pictures

Owners and Caregivers may upload JPEG, PNG, or WebP. Minilog corrects orientation, removes metadata, crops to a square, creates a small WebP derivative, discards the original, and stores no image history. Replacement and removal delete the previous derivative immediately.

## PiyoLog migration

The MVP accepts English and Japanese PiyoLog day or month text exports from iOS and Android. An import batch targets one Baby and a user-confirmed source time zone.

The workflow is upload, parse, preview, and confirm. Preview shows date range, counts by type, unknown lines, reconciliation totals, warnings, and conflicts. Malformed and unsupported lines are never silently discarded.

Recognized lines become typed care records attributed to `PiyoLog import`. Unrecognized lines become read-only Imported care records retaining raw source information. Date-only daily notes become read-only Imported daily notes. Corrected imported records are marked modified and require an explicit keep-or-replace choice during re-import.

Exact-file hashes make identical imports idempotent. Revised imports may replace only unchanged records from an earlier PiyoLog import for affected dates, never native Minilog records. The Owner may delete a retained source file without deleting resulting records.

The migration does not promise account cloning. PiyoLog settings, caregiver identities, active timers, edit history, PDFs, and photos are excluded.

## Ownership, export, and deletion

- Lossless Minilog export is a versioned ZIP containing structured JSON, profile pictures, retained import sources, checksums, and a format version.
- The same package supports restore and server-to-server migration.
- A flattened timeline CSV supports human inspection and analysis but is not a restore format.
- The MVP documents safe manual SQLite backup and restore.
- Baby deletion is Owner-only, offers export first, requires typed confirmation, and permanently removes the Baby, picture, and associated records.
- Household deletion permanently removes all application-owned data.

## Explicit MVP exclusions

The committed exclusions are maintained in [NICE-TO-HAVE.md](./NICE-TO-HAVE.md). Being listed there is not a delivery promise.

## Definition of done

The MVP is complete only when:

- Every stated workflow and care type works across supported mobile and desktop browsers.
- Offline creation, foreground polling, stale edits, concurrent timers, deletion, PiyoLog reconciliation, export/restore, and failed migrations have automated coverage.
- Fresh install and upgrade are verified through Docker Compose on Linux `amd64` and `arm64`.
- Accessibility checks and one-handed mobile Playwright flows pass.
- Runtime network tests prove there are no third-party requests.
- The deployment, recovery, security, privacy, and known-limit documentation matches the shipped behavior.
