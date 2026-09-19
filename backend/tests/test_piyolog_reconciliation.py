from minilog.services.piyolog import parse_piyolog, reconciliation_totals


def test_piyolog_reconciliation_totals_preserve_entered_facts() -> None:
    parsed = parse_piyolog(
        b"September 8, 2026\n"
        b"07:00 Sleep\n"
        b"08:15 Wake up\n"
        b"08:30 Bottle: 120 ml formula\n"
        b"09:00 Diaper: wet\n"
        b"09:30 Custom event\n"
    )

    assert reconciliation_totals(parsed) == {
        "bottle_feeding_ml": 120,
        "bottle_feeding_records": 1,
        "diaper_change_records": 1,
        "dirty_diapers": 0,
        "imported_care_record_records": 1,
        "sleep_minutes": 75,
        "sleep_records": 1,
        "wet_diapers": 1,
    }
