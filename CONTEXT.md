# Baby Care Logging

This context describes the private, shared record of a household's day-to-day care for its babies.

## Language

**Household**:
The family unit whose caregivers share access to its babies and care records. One deployment serves one household.
_Avoid_: Account, tenant, family account

**Baby**:
A child whose daily care is recorded by the household. A household may have more than one baby.
_Avoid_: Profile, subject, patient

**Profile picture**:
An optional image used to recognize a baby in selection controls and on Today. It is not part of a photo album or diary.
_Avoid_: Avatar, baby photo

**Owner**:
A caregiver who administers the household and has full access to its records and settings.
_Avoid_: Superuser, root user

**Caregiver**:
A person who can view and record care for the household's babies but cannot administer the household.
_Avoid_: Member, regular user

**Care record**:
A timestamped observation or action concerning a baby, such as feeding, sleeping, a diaper change, pumping, medication, a measurement, or a note.
_Avoid_: Log entry, event, activity

**Timed care record**:
A care record with a start and an optional end. A timed care record without an end is active.
_Avoid_: Timer, session

**Feeding**:
A care record of nourishment given to a baby. Breastfeeding, bottle feeding, and solid food are distinct kinds of feeding.
_Avoid_: Meal

**Breastfeeding**:
A timed feeding made up of ordered left- or right-side intervals. A household may record an estimated amount, but time by side is the primary observation.
_Avoid_: Nursing session, breastfeed event

**Bottle feeding**:
A feeding that records how much breast milk, formula, mixed contents, or another liquid a baby consumed, and optionally how much was offered.
_Avoid_: Bottle

**Solid-food feeding**:
A feeding described by the foods offered, with an optional amount and observed reaction note. It carries no inferred nutrition or allergen meaning.
_Avoid_: Meal, solids

**Diaper change**:
A care record of a wet diaper, dirty diaper, or both, with optional descriptive observations.
_Avoid_: Diaper, bowel movement

**Pumping**:
A timed care record of milk expressed for the selected baby. It appears alongside that baby's other care records and contributes to the baby's trends.
_Avoid_: Feeding, breast-pump session

**Medication administration**:
A care record stating that a caregiver gave a baby a particular amount of medicine. It is an observation, not a prescription, schedule, reminder, or dosage recommendation.
_Avoid_: Medication, dose schedule

**Measurement**:
A numeric observation of a baby's weight, height, or temperature, preserving both its canonical value and the value and unit entered by the caregiver.
_Avoid_: Vital, health metric

**Today**:
The selected baby's care records grouped into the current calendar day in the household's configured time zone.
_Avoid_: Dashboard, home feed

**Import batch**:
One reviewed migration of a source file into a selected baby's history, retaining its provenance and reconciliation report.
_Avoid_: Upload, migration job

**Imported care record**:
A read-only care record that preserves an unrecognized PiyoLog entry without pretending to understand its type-specific meaning.
_Avoid_: Unknown event, fallback record

**Imported daily note**:
A date-scoped, read-only note preserved from a PiyoLog export when the source provides no occurrence time.
_Avoid_: Diary entry, care record
