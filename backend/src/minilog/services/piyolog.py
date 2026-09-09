from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from minilog.models import RecordType
from minilog.schemas import (
    BottleFeedingCreate,
    BreastfeedingCreate,
    BreastfeedingIntervalInput,
    DiaperChangeCreate,
    MeasurementCreate,
    MedicationAdministrationCreate,
    PumpingCreate,
    SleepCreate,
    SolidFoodFeedingCreate,
)

DATE_PATTERNS = (
    re.compile(r"^(?P<y>20\d{2})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})(?:\D.*)?$"),
    re.compile(r"^(?P<y>20\d{2})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日(?:.*)?$"),
)
ENGLISH_DATE_PATTERNS = ("%A, %B %d, %Y", "%B %d, %Y", "%a, %b %d, %Y", "%b %d, %Y")
TIME_LINE = re.compile(r"^(?P<h>\d{1,2}):(?P<m>\d{2})\s+(?P<body>.+?)\s*$")
JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
NUMBER_UNIT = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>ml|mL|g|kg|cm|mm|°?[CF]|℃|℉)", re.I
)


@dataclass
class ParsedEntry:
    source_line: int
    local_at: datetime
    raw_line: str
    raw_label: str
    raw_details: str | None
    kind: str
    values: dict[str, object] = field(default_factory=dict)
    ended_local_at: datetime | None = None


@dataclass
class ParsedDailyNote:
    source_line: int
    local_date: date
    body: str


@dataclass
class ParsedPiyoLog:
    source_hash: str
    locale: str
    entries: list[ParsedEntry]
    daily_notes: list[ParsedDailyNote]
    unplaced_lines: list[dict[str, object]]
    warnings: list[str]

    @property
    def dates(self) -> list[date]:
        return [item.local_at.date() for item in self.entries] + [
            item.local_date for item in self.daily_notes
        ]

    @property
    def counts(self) -> dict[str, int]:
        counts = Counter(item.kind for item in self.entries)
        if self.daily_notes:
            counts["daily_note"] = len(self.daily_notes)
        if self.unplaced_lines:
            counts["unplaced_line"] = len(self.unplaced_lines)
        return dict(sorted(counts.items()))

    @property
    def unknown_lines(self) -> list[dict[str, object]]:
        unknown = [
            {"line": item.source_line, "text": item.raw_line, "placed": True}
            for item in self.entries
            if item.kind == "imported_care_record"
        ]
        return unknown + self.unplaced_lines


def decode_source(source: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "shift_jis"):
        try:
            return source.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=422, detail="piyolog_text_encoding_unsupported")


def parse_date_header(line: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.match(line)
        if match:
            try:
                return date(int(match["y"]), int(match["m"]), int(match["d"]))
            except ValueError:
                return None
    normalized = re.sub(
        r"\s+",
        " ",
        line.replace("st,", ",").replace("nd,", ",").replace("rd,", ",").replace("th,", ","),
    )
    for pattern in ENGLISH_DATE_PATTERNS:
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


def duration_minutes(text: str) -> int | None:
    hours = re.search(r"(\d+)\s*(?:hours?|hrs?|時間)", text, re.I)
    minutes = re.search(r"(\d+)\s*(?:minutes?|mins?|分)", text, re.I)
    if not hours and not minutes:
        return None
    return (int(hours.group(1)) * 60 if hours else 0) + (int(minutes.group(1)) if minutes else 0)


def split_label(body: str) -> tuple[str, str]:
    parts = re.split(r"\s{2,}|\t+|\s*[:\uff1a]\s*", body, maxsplit=1)
    if len(parts) == 1:
        words = body.split(maxsplit=1)
        return words[0], words[1] if len(words) > 1 else ""
    return parts[0], parts[1]


def classify_entry(line_number: int, local_at: datetime, raw_line: str) -> ParsedEntry:
    body = TIME_LINE.match(raw_line)["body"]  # type: ignore[index]
    label, details = split_label(body)
    folded = f"{label} {details}".casefold()
    base = dict(
        source_line=line_number,
        local_at=local_at,
        raw_line=raw_line,
        raw_label=label,
        raw_details=details or None,
    )

    if any(word in folded for word in ("wake", "awake", "起きる", "起床")):
        return ParsedEntry(**base, kind="wake_marker")
    if any(word in folded for word in ("sleep", "asleep", "寝る", "睡眠", "就寝")):
        return ParsedEntry(**base, kind="sleep_marker")
    if any(word in folded for word in ("breast", "nursing", "母乳", "授乳")):
        left = re.search(r"(?:left|左)\D{0,8}(\d+)\s*(?:min|分)", folded)
        right = re.search(r"(?:right|右)\D{0,8}(\d+)\s*(?:min|分)", folded)
        total = (int(left.group(1)) if left else 0) + (int(right.group(1)) if right else 0)
        if total == 0:
            total = duration_minutes(folded) or 0
        values: dict[str, object] = {
            "left_minutes": int(left.group(1)) if left else 0,
            "right_minutes": int(right.group(1)) if right else 0,
        }
        return ParsedEntry(
            **base,
            kind="breastfeeding" if total else "imported_care_record",
            values=values,
            ended_local_at=local_at + timedelta(minutes=total) if total else None,
        )
    if any(word in folded for word in ("bottle", "formula", "milk", "ミルク", "搾母乳")):
        amount = NUMBER_UNIT.search(folded)
        if amount and amount["unit"].casefold() == "ml":
            contents = (
                "breast_milk"
                if any(word in folded for word in ("expressed", "breast", "搾母乳"))
                else "formula"
            )
            return ParsedEntry(
                **base,
                kind="bottle_feeding",
                values={
                    "consumed_ml": int(Decimal(amount["value"].replace(",", "."))),
                    "contents": contents,
                },
            )
    if any(word in folded for word in ("solid", "food", "meal", "離乳食", "ごはん", "おやつ")):
        return ParsedEntry(**base, kind="solid_food_feeding", values={"foods": details or label})
    if any(
        word in folded for word in ("diaper", "wet", "pee", "poop", "おしっこ", "うんち", "両方")
    ):
        wet = any(word in folded for word in ("wet", "pee", "おしっこ", "両方"))
        dirty = any(word in folded for word in ("dirty", "poop", "うんち", "両方"))
        return ParsedEntry(**base, kind="diaper_change", values={"is_wet": wet, "is_dirty": dirty})
    if any(word in folded for word in ("pump", "pumping", "搾乳")):
        amount = NUMBER_UNIT.search(folded)
        minutes = duration_minutes(folded)
        return ParsedEntry(
            **base,
            kind="pumping",
            values={
                "expressed_ml": int(Decimal(amount["value"].replace(",", ".")))
                if amount and amount["unit"].casefold() == "ml"
                else None
            },
            ended_local_at=local_at + timedelta(minutes=minutes or 0),
        )
    if any(
        word in folded
        for word in ("temperature", "temp", "体温", "weight", "体重", "height", "身長")
    ):
        amount = NUMBER_UNIT.search(folded)
        if amount:
            if any(word in folded for word in ("weight", "体重")):
                kind = "weight"
            elif any(word in folded for word in ("height", "身長")):
                kind = "height"
            else:
                kind = "temperature"
            unit = amount["unit"].replace("℃", "celsius").replace("℉", "fahrenheit")
            return ParsedEntry(
                **base,
                kind="measurement",
                values={
                    "measurement_kind": kind,
                    "value": amount["value"].replace(",", "."),
                    "unit": unit,
                },
            )
    if any(word in folded for word in ("medicine", "medication", "薬", "くすり")):
        amount = NUMBER_UNIT.search(folded)
        if amount:
            return ParsedEntry(
                **base,
                kind="medication_administration",
                values={
                    "name": label,
                    "value": amount["value"].replace(",", "."),
                    "unit": amount["unit"],
                },
            )
    return ParsedEntry(**base, kind="imported_care_record")


def parse_piyolog(source: bytes) -> ParsedPiyoLog:
    text = decode_source(source).replace("\r\n", "\n").replace("\r", "\n")
    locale = "ja" if len(JAPANESE.findall(text)) > 3 else "en"
    current_date: date | None = None
    entries: list[ParsedEntry] = []
    notes: list[ParsedDailyNote] = []
    unplaced: list[dict[str, object]] = []
    pending_sleep: ParsedEntry | None = None

    for line_number, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if not line:
            continue
        parsed_date = parse_date_header(line)
        if parsed_date:
            current_date = parsed_date
            continue
        note = re.match(r"^(?:diary|memo|note|育児日記|日記)\s*[:\uff1a]\s*(.+)$", line, re.I)
        if note and current_date:
            notes.append(ParsedDailyNote(line_number, current_date, note.group(1).strip()))
            continue
        timed = TIME_LINE.match(line)
        if not timed or current_date is None:
            unplaced.append({"line": line_number, "text": line, "placed": False})
            continue
        try:
            local_at = datetime.combine(current_date, datetime.min.time()).replace(
                hour=int(timed["h"]), minute=int(timed["m"])
            )
        except ValueError:
            unplaced.append({"line": line_number, "text": line, "placed": False})
            continue
        entry = classify_entry(line_number, local_at, line)
        if entry.kind == "sleep_marker":
            if pending_sleep is not None:
                pending_sleep.kind = "imported_care_record"
                entries.append(pending_sleep)
            pending_sleep = entry
        elif entry.kind == "wake_marker":
            if pending_sleep is None or local_at <= pending_sleep.local_at:
                entry.kind = "imported_care_record"
                entries.append(entry)
            else:
                pending_sleep.kind = "sleep"
                pending_sleep.ended_local_at = local_at
                entries.append(pending_sleep)
                pending_sleep = None
        else:
            entries.append(entry)
    if pending_sleep is not None:
        pending_sleep.kind = "imported_care_record"
        entries.append(pending_sleep)

    warnings = []
    if unplaced:
        warnings.append(
            "Some lines had no usable date and time; they remain in the retained source and report."
        )
    if any(item.kind == "imported_care_record" for item in entries):
        warnings.append("Unknown timed entries will be preserved as read-only imported records.")
    return ParsedPiyoLog(
        hashlib.sha256(source).hexdigest(), locale, entries, notes, unplaced, warnings
    )


def localize(value: datetime, time_zone: str) -> datetime:
    try:
        return value.replace(tzinfo=ZoneInfo(time_zone))
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="unknown_time_zone") from exc


def entry_to_payload(entry: ParsedEntry, baby_id: str, time_zone: str):
    occurred = localize(entry.local_at, time_zone)
    ended = localize(entry.ended_local_at, time_zone) if entry.ended_local_at else None
    offset = int((occurred.utcoffset() or timedelta()).total_seconds() / 60)
    common = {
        "baby_id": baby_id,
        "occurred_at": occurred,
        "ended_at": ended,
        "local_offset_minutes": offset,
    }
    values = entry.values
    match entry.kind:
        case "breastfeeding":
            cursor = occurred
            intervals = []
            for side in ("left", "right"):
                minutes = int(values.get(f"{side}_minutes", 0))
                if minutes:
                    finish = cursor + timedelta(minutes=minutes)
                    intervals.append(
                        BreastfeedingIntervalInput(side=side, started_at=cursor, ended_at=finish)
                    )
                    cursor = finish
            return BreastfeedingCreate(
                record_type=RecordType.BREASTFEEDING, intervals=intervals, **common
            )
        case "bottle_feeding":
            return BottleFeedingCreate(
                record_type=RecordType.BOTTLE_FEEDING,
                consumed_ml=values["consumed_ml"],
                contents=values["contents"],
                **common,
            )
        case "solid_food_feeding":
            return SolidFoodFeedingCreate(
                record_type=RecordType.SOLID_FOOD_FEEDING, foods=values["foods"], **common
            )
        case "sleep":
            return SleepCreate(record_type=RecordType.SLEEP, **common)
        case "diaper_change":
            return DiaperChangeCreate(
                record_type=RecordType.DIAPER_CHANGE,
                is_wet=values["is_wet"],
                is_dirty=values["is_dirty"],
                **common,
            )
        case "pumping":
            return PumpingCreate(
                record_type=RecordType.PUMPING, expressed_ml=values["expressed_ml"], **common
            )
        case "measurement":
            return MeasurementCreate(
                record_type=RecordType.MEASUREMENT,
                kind=values["measurement_kind"],
                entered_value=values["value"],
                entered_unit=values["unit"],
                **common,
            )
        case "medication_administration":
            return MedicationAdministrationCreate(
                record_type=RecordType.MEDICATION_ADMINISTRATION,
                medicine_name=values["name"],
                amount_value=values["value"],
                unit_code=values["unit"],
                **common,
            )
    return None
