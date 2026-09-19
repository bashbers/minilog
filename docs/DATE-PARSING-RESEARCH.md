# Localized PiyoLog date parsing research

Research date: 2026-09-12

## Decision

Use [`dateparser`](https://dateparser.readthedocs.io/en/latest/) as a constrained fallback for date-header recognition if Minilog expands PiyoLog import beyond explicitly supported adapters. Keep the current exact numeric, Japanese, English, and Dutch parsing paths first; invoke `dateparser` only for lines shaped like complete date headers, with only its absolute-date parser enabled and day, month, and year required.

This is the broadest practical Python option, not a guarantee of every future export. Dateparser supports more than 200 language locales, autodetection, explicit language/locale constraints, and its official usage documentation includes the closely analogous Dutch input `vr jan 24, 2014`, detected as `nl`. [Dateparser overview](https://dateparser.readthedocs.io/en/latest/), [supported locales](https://dateparser.readthedocs.io/en/latest/supported_locales.html), [Dutch example](https://dateparser.readthedocs.io/en/latest/usage.html)

No date library can guarantee an unknown future PiyoLog format. Such a guarantee would require PiyoLog to supply a locale identifier and a stable date grammar or, preferably, a machine-readable date. The sample combines English record labels with a Dutch date header (`di 1 sep 2026`), so the date locale is apparently not reliably inferable from the record-label language. That makes short-header language detection inherently ambiguous. Minilog should retain preview, provenance, and unknown-line behavior, and offer an explicit source-locale choice if automatic recognition is ambiguous.

## Comparison

| Option | Language and locale breadth | Determinism and locale requirement | Weight, maintenance, Python 3.12–3.13 | Assessment |
| --- | --- | --- | --- |
| Python `datetime.strptime` + `locale` | Parses localized `%a`, `%A`, `%b`, and `%B`, but only through locales installed and named by the host platform. | Requires changing the process-wide `LC_TIME`; `setlocale()` is not thread-safe, affects other threads, and available locale names vary by system. | No dependency; maintained with Python and therefore compatible with 3.12–3.13. | Unsuitable for a concurrent web service and non-portable across Minilog deployments. |
| Babel 2.18 | Ships broad CLDR-derived locale data and exposes localized day/month names. | Accepts an explicit locale, but `babel.dates.parse_date()` still supports only numeric dates; using Babel for these headers would require a custom tokenizer/parser and separate locale selection or detection. | Current production/stable release supports Python 3.12–3.14, has no runtime dependency on modern Python, but its wheel is 10.2 MB. | Good locale-data source, not a direct fix. More bespoke code and a larger package than `dateparser`. |
| `dateparser` 1.4.3 | More than 200 locales, built-in detection, explicit `languages`/`locales`, Unicode normalization, and optional non-Gregorian support. | Can be narrowed to absolute dates and require all three date parts. Detection is still heuristic when no locale is supplied; numeric dates remain culturally ambiguous. | Current production/stable release explicitly supports Python 3.12–3.14. The direct wheel is 322.4 kB, with four runtime dependencies: `python-dateutil`, `pytz`, `regex`, and `tzlocal`. | Best practical fit, provided it is gated and configured strictly. |
| `python-dateutil` 2.9.0.post0 | The default `parserinfo` contains English weekday and month names only. Other languages need custom subclasses and hand-maintained token tables. | `dayfirst` and `yearfirst` control numeric ambiguity; missing fields are filled from a default datetime and fuzzy parsing deliberately ignores tokens. | Small pure-Python wheel (229.9 kB) plus `six`; latest release is from 2024 and its published classifiers stop at Python 3.12. | Flexible English parser, but it does not solve localization. |
| ICU through PyICU 2.16.2 | ICU provides locale data for more than 300 locales and culture-specific date parsing. | Needs an explicit locale and format/style; it does not solve language detection. ICU itself warns against parsing localized strings and can select locale-specific calendars, which could conflict with an export that always uses Gregorian years. | Current PyICU release is a 268.2 kB source distribution wrapping native ICU. Installation requires ICU libraries/headers, `pkg-config`, and a C++ build; PyPI declares no `Requires-Python` or version classifiers. | Broadest data but disproportionate deployment complexity, especially for Linux `amd64` and `arm64` images. |

The standard-library behavior and risks above are documented by Python: date directives are locale-sensitive, supported directives vary by platform, locale availability is system-dependent, and changing locale in a library routine is discouraged because it is process-wide and affects other threads. [Python date directives](https://docs.python.org/3.13/library/datetime.html#strftime-and-strptime-format-codes), [Python locale caveats](https://docs.python.org/3.13/library/locale.html#background-details-hints-tips-and-caveats)

Babel exposes locale-specific day and month tables, but the tagged 2.18 source explicitly marks textual month-name parsing as unsupported. Its current compatibility, release date, wheel size, and packaging data are published on PyPI. [Babel day/month APIs](https://babel.pocoo.org/en/latest/api/dates.html), [Babel 2.18 parser limitation](https://github.com/python-babel/babel/blob/v2.18.0/babel/dates.py#L1209-L1210), [Babel PyPI metadata](https://pypi.org/project/babel/)

Dateutil describes its parser as forgiving and documents that absent fields are borrowed from a default value. Its default `parserinfo` lists only English `MONTHS` and `WEEKDAYS`; localization would therefore recreate the per-language adapter work Minilog is trying to avoid. [Dateutil parser and `parserinfo`](https://dateutil.readthedocs.io/en/stable/parser.html), [dateutil PyPI metadata](https://pypi.org/project/python-dateutil/)

ICU supports more than 300 locales and localized date parsing, but locale-sensitive services depend on an explicit locale. ICU also notes that the selected calendar may vary by locale and calls parsing localized strings generally bad practice. PyICU currently ships only source and documents the required native toolchain and ICU installation. [ICU breadth and date parsing](https://unicode-org.github.io/icu/userguide/icu4c/), [ICU formatting/parsing caveats](https://unicode-org.github.io/icu/userguide/format_parse/), [PyICU packaging and build requirements](https://pypi.org/project/pyicu/)

## Recommended integration constraints

If implemented, use a new `DateDataParser` per uploaded export so locale discovery can be reused consistently within that file without leaking cross-import state. Preserve exact parsers as the preferred path, then constrain the fallback approximately as follows:

```python
settings = {
    "PARSERS": ["absolute-time"],
    "STRICT_PARSING": True,
    "REQUIRE_PARTS": ["day", "month", "year"],
}
```

Dateparser documents `PARSERS=['absolute-time']` as the absolute-date-only engine and documents both strict settings as rejecting incomplete dates. Its default behavior requires the whole input to be a date; do not enable `IGNORE_SURROUNDING_TEXT` or use `search_dates()`, because the official documentation warns that ignored text can create false positives. [Dateparser parser selection](https://dateparser.readthedocs.io/en/latest/settings.html#other-settings), [strictness and false-positive warning](https://dateparser.readthedocs.io/en/latest/settings.html#handling-incomplete-dates)

In addition:

- Pre-gate the fallback to a short line containing an explicit four-digit year and plausible date-header structure. Do not run natural-language parsing over every imported line.
- Keep the existing 10 MB upload cap and add a small per-line length cap before invoking the parser to bound regex work.
- If PiyoLog ever supplies a locale, pass it through `locales=[...]`; dateparser then uses only those locales. Without one, record the detected locale and require it to remain consistent across an export. [Dateparser API](https://dateparser.readthedocs.io/en/latest/dateparser.html#dateparser.parse)
- Validate the resulting calendar date, explicit year, and—where the locale/token can be identified—the weekday. Reject conflicting or multiple interpretations instead of selecting one silently.
- Continue to test real exported fixtures for every encountered locale and platform. Library locale coverage is not a contract for PiyoLog's syntax.
- Pin at least `dateparser>=1.4.3,<2`. Versions 1.4.0–1.4.1 removed unsafe packaged-data deserialization and `eval()` use and fixed a quadratic-regex/ReDoS issue; 1.4.3 also fixed concurrent cache/settings leakage. [Dateparser release history and security fixes](https://pypi.org/project/dateparser/)

## Bottom line

`dateparser` can replace the open-ended sequence of hand-written month/weekday tables for the foreseeable localized export set, including the supplied Dutch case. It should be treated as a strict, auditable date-header recognizer behind structural checks—not as a universal parser. A source-locale selector remains the only reliable fallback when the export itself does not identify its locale.
