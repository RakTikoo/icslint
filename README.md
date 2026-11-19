# icslint

**Check an `.ics` file against the requirements RFC 5545 actually states and the import failures Google, Outlook and Apple Calendar are documented to have — locally, in batch, in CI — and say nothing about anything that cannot be proven from the file alone.**

## Install

```console
$ pip install git+https://github.com/RakTikoo/icslint
```

Needs Python 3.10+. Zero dependencies. Everything runs **offline**,
on your machine: no upload, no network, no timezone database.

## Usage

```console
$ icslint check <file-or-folder> [--strict] [--format text|json]
```

- A folder is scanned recursively for `*.ics` files (case-insensitive).
- Every finding prints the file, the physical line where the offending
  content line starts, the component, the rule ID, the severity, a
  plain-language explanation, and its source — an RFC 5545 section, or
  a named importer source labelled **Importer behaviour**. The two are
  never blended silently: a finding cites the RFC, or it cites an
  importer, and says which.
- Exit codes: `0` = no errors (warnings allowed), `1` = at least one
  error (or any warning under `--strict`), `2` = usage error or
  unreadable input, always as a one-line message, never a traceback.
- `--format json` emits the same findings as JSON for CI tooling.

## Demo

`examples/broken.ics` is a small calendar with five seeded defects.
Actual output:

```console
$ icslint check examples/broken.ics
examples/broken.ics:4: ERROR V02 [VEVENT[UID=broken-1@example.com]] This VEVENT has no DTSTAMP. Every VEVENT, VTODO, VJOURNAL and VFREEBUSY must include one — a missing DTSTAMP is the documented cause of Google Calendar's 'Unable to launch event' failure. (RFC 5545 §3.6.1–§3.6.4 ABNFs; §3.8.7.2; importer behaviour: Terence Eden, Jul 2026 (missing DTSTAMP is the documented cause of Google's 'Unable to launch event'))
examples/broken.ics:14: ERROR E02 [VEVENT[UID=broken-2@example.com]] DTEND (20260601T090000Z) is not later than DTSTART (20260601T100000Z). The end of an event must be later than its start. (RFC 5545 §3.8.2.2 (and §3.8.2.3 for DUE); importer behaviour: csvtoics.app, Aug 2026 §5 (equal all-day dates are a zero-length event some importers drop))
examples/broken.ics:21: ERROR R03 [VEVENT[UID=broken-3@example.com]] This RRULE carries both COUNT and UNTIL. They must not occur in the same recurrence rule — pick one. (RFC 5545 §3.3.10 ('MUST NOT occur in the same recur'); importer behaviour: csvtoics.app, Aug 2026 §12)
examples/broken.ics:22: WARNING W01 [VEVENT[UID=broken-3@example.com]] SUMMARY contains an unescaped ';'. In a TEXT value, ';' and ',' must be escaped with a backslash — Outlook truncates the value at an unescaped semicolon. (RFC 5545 §3.3.11 (MUST be escaped); importer behaviour: SpreadEvent, Apr 2026 (Outlook truncates the value at an unescaped semicolon))
examples/broken.ics:25: ERROR V04 [VEVENT[UID=broken-3@example.com]] UID 'broken-3@example.com' is used by more than one component with the same RECURRENCE-ID (none). A UID must be globally unique; importers treat a repeat as an update to the first event, not as a new one. Components sharing a UID with different RECURRENCE-IDs are legal overrides and are not flagged. (RFC 5545 §3.8.4.7 and §3.8.4.4; importer behaviour: csvtoics.app, Aug 2026 §6 (Google treats a repeated UID as an update; Outlook may refuse))
icslint: 1 file checked, 4 errors, 1 warning
$ echo $?
1
```

And a clean file:

```console
$ icslint check examples/clean.ics
icslint: 1 file checked, no findings
```

## Honest limits

These are not fine print — they define what this tool is.

- **No recurrence expansion.** icslint never generates the instances
  an RRULE describes. It checks the rule's syntax and the form
  cross-checks the spec states (COUNT and UNTIL together, UNTIL in
  the wrong form for DTSTART, forbidden part combinations), but it
  will **not** tell you whether an EXDATE matches a real occurrence,
  whether a RECURRENCE-ID names a generated instance, or whether a
  recurrence set is empty. Do not rely on it for any of those.
- **No DST / VTIMEZONE transition semantics.** icslint checks that
  VTIMEZONE components exist and are well-formed. It never judges
  whether an offset is *correct* for a zone, whether a local time
  falls in a DST gap or a repeated hour, or what instant a TZID time
  "really" is. It will **not** tell you whether a repeated event
  lands at the right local time across a clock change, and it stays
  silent on DTEND-vs-DTSTART ordering whenever comparing the two
  would need a zone's offsets (different TZIDs, or UTC vs TZID).
  Same-form pairs only.
- **No fixing, no conversion.** The tool reports; it never edits
  your file.
- **Severity is calibrated, and the calibration is stated.** An
  ERROR is an RFC MUST / MUST NOT / REQUIRED / ABNF violation, or a
  hard import failure a named source documents. A WARNING is an RFC
  SHOULD / SHOULD NOT, an importer-documented soft failure, or an
  RFC MUST that importers routinely waive through a defined
  fallback. The worked example is T03 (a TZID with no VTIMEZONE in
  the file): the RFC says a VTIMEZONE MUST be supplied, but Google,
  Outlook and Apple resolve known IANA names without one — so it is
  a warning, not an error.
- **Citations say what the source actually says.** Where an importer
  source's own lint is *more lenient* than icslint — csvtoics.app's
  validator, for instance, only *warns* on a duplicate UID, a
  missing DTSTAMP and a non-2.0 VERSION, where icslint reports
  errors — the error rests on the RFC MUST, and the README and the
  findings do not imply the importer source calls it an error.
- **One rule is advice, not a violation.** S04 (a fold that splits a
  multi-byte UTF-8 character) is flagged as a warning because naive
  parsers garble such characters. RFC 5545 does not forbid the
  generator from doing it — it obliges parsers to cope — and the
  finding says so.
- **Deliberate silences.** A missing SUMMARY, a missing DTEND (the
  spec defines defaults), floating times, lowercase property names
  and values, `X-` properties, an RRULE with neither COUNT nor
  UNTIL, COUNT=0, a negative SEQUENCE, and identical duplicate
  VTIMEZONE definitions are all legal, and icslint says nothing
  about any of them. A conforming file produces **zero findings** —
  that is the tested guarantee, not an aspiration: the test suite
  runs a corpus of real-world-shaped valid files (Google, Outlook
  and Apple exporter shapes, folded multi-byte UTF-8, all-day
  events, UID-sharing overrides, floating times, a leap second, the
  RFC's own VTIMEZONE example) and requires silence on every one.

## Use with an AI agent

This repo ships a [SKILL.md](SKILL.md) written to the Agent Skills open standard. If your coding agent supports skills, point it at this repo and it can install icslint, run it on your calendar files, and read the findings for you. The skill works when the repo is cloned under its real name (`icslint`) — a skill's name must match its folder.

## Rules

67 rules: 58 errors, 9 warnings. Every rule cites RFC 5545 or a
named, dated importer source (Terence Eden, Jul 2026; iCal
Converter, Aug 2026; csvtoics.app, Aug 2026; SpreadEvent, Apr
2026). The *Source* column says which kind each rule is.

| ID | Check | Severity | Source |
|---|---|---|---|
| S01 | Line ends with a bare LF instead of CRLF (or the final line has no CRLF at all) | Error | RFC 5545 + importer behaviour |
| S02 | Line ends with a bare CR instead of CRLF | Error | RFC 5545 |
| S03 | Physical line longer than 75 octets, not folded | Warning | RFC 5545 + importer behaviour |
| S04 | Fold falls inside a multi-byte UTF-8 character; naive parsers garble it | Warning | Robustness advice |
| S05 | First line begins with a space or tab (a fold continuation with nothing to continue) | Error | RFC 5545 |
| S06 | Blank line inside the iCalendar object | Error | RFC 5545 |
| S07 | Content line has no ':' separating the property name from its value | Error | RFC 5545 |
| S08 | File is not valid UTF-8 | Error | RFC 5545 + importer behaviour |
| S09 | File starts with a UTF-8 byte-order mark | Warning | Importer behaviour |
| S10 | A property that may occur at most once in its component occurs twice | Error | RFC 5545 |
| C01 | Content outside a VCALENDAR object, or an object not opened/closed by BEGIN/END:VCALENDAR | Error | RFC 5545 + importer behaviour |
| C02 | Unclosed, mismatched or illegally nested BEGIN/END components | Error | RFC 5545 |
| C03 | VCALENDAR has no PRODID | Error | RFC 5545 |
| C04 | VCALENDAR has no VERSION | Error | RFC 5545 |
| C05 | VERSION is not 2.0 | Error | RFC 5545 + importer behaviour |
| C06 | VCALENDAR contains no calendar component at all | Error | RFC 5545 |
| V01 | VEVENT/VTODO/VJOURNAL/VFREEBUSY has no UID (or an empty one) | Error | RFC 5545 |
| V02 | VEVENT/VTODO/VJOURNAL/VFREEBUSY has no DTSTAMP | Error | RFC 5545 + importer behaviour |
| V03 | VEVENT has no DTSTART and the VCALENDAR specifies no METHOD | Error | RFC 5545 + importer behaviour |
| V04 | Two components share the same UID and the same RECURRENCE-ID | Error | RFC 5545 + importer behaviour |
| V05 | DTSTAMP (or CREATED / LAST-MODIFIED) is not in UTC form | Error | RFC 5545 |
| V06 | VTODO carries a DURATION but no DTSTART | Error | RFC 5545 |
| V07 | VFREEBUSY DTSTART, DTEND or FREEBUSY value is not in UTC form | Error | RFC 5545 |
| D01 | DATE value is malformed or impossible (e.g. 20260230) | Error | RFC 5545 + importer behaviour |
| D02 | DATE-TIME value is malformed (missing T, hyphen/colon separators, UTC-offset suffix, out-of-range fields) | Error | RFC 5545 |
| D03 | VALUE= parameter disagrees with the value's actual form | Error | RFC 5545 |
| D04 | DTEND, DUE or RECURRENCE-ID has a different value kind (DATE vs DATE-TIME) from DTSTART | Error | RFC 5545 |
| D05 | DTEND, DUE or RECURRENCE-ID is local where DTSTART is UTC, or UTC where DTSTART is local | Error | RFC 5545 |
| E01 | VEVENT carries both DTEND and DURATION | Error | RFC 5545 |
| E02 | DTEND (or DUE) is not later than DTSTART | Error | RFC 5545 + importer behaviour |
| E03 | DURATION value is malformed (including Y/M designators, which iCalendar does not support) | Error | RFC 5545 |
| E04 | VEVENT/VTODO DURATION is negative or zero | Error | RFC 5545 |
| E05 | DTSTART is a DATE but DURATION is not a whole dur-day or dur-week value | Error | RFC 5545 |
| T01 | TZID parameter applied to a UTC (Z) value | Error | RFC 5545 |
| T02 | TZID parameter applied to a DATE value | Error | RFC 5545 |
| T03 | TZID referenced but no VTIMEZONE in the file defines it | Warning | RFC 5545 + importer behaviour |
| T04 | Two VTIMEZONE components define the same TZID with different bodies | Error | RFC 5545 + importer behaviour |
| T05 | VTIMEZONE has no TZID property | Error | RFC 5545 |
| T06 | VTIMEZONE has no STANDARD or DAYLIGHT sub-component | Error | RFC 5545 |
| T07 | STANDARD/DAYLIGHT is missing DTSTART, TZOFFSETFROM or TZOFFSETTO | Error | RFC 5545 |
| T08 | STANDARD/DAYLIGHT DTSTART is not a plain local time (carries a Z or a TZID) | Error | RFC 5545 |
| T09 | TZOFFSETFROM/TZOFFSETTO value is malformed (bad form, second = 60, or negative zero) | Error | RFC 5545 |
| R01 | RRULE has no FREQ rule part | Error | RFC 5545 |
| R02 | FREQ is not one of SECONDLY, MINUTELY, HOURLY, DAILY, WEEKLY, MONTHLY, YEARLY | Error | RFC 5545 + importer behaviour |
| R03 | RRULE carries both COUNT and UNTIL | Error | RFC 5545 + importer behaviour |
| R04 | The same rule part occurs twice in one RRULE | Error | RFC 5545 |
| R05 | RRULE contains a rule part outside the ABNF set | Warning | RFC 5545 + importer behaviour |
| R06 | UNTIL's value kind (DATE vs DATE-TIME) disagrees with DTSTART's | Error | RFC 5545 |
| R07 | UNTIL's UTC-ness disagrees with DTSTART's form (never applied inside STANDARD/DAYLIGHT — see R12) | Error | RFC 5545 + importer behaviour |
| R08 | A rule part's value is out of range, not a number, or not a valid weekday token | Error | RFC 5545 |
| R09 | Forbidden rule-part/FREQ combination (e.g. BYMONTHDAY with FREQ=WEEKLY, BYSETPOS with no other BYxxx part) | Error | RFC 5545 |
| R10 | Component carries more than one RRULE property | Warning | RFC 5545 |
| R11 | Component carries an RRULE but no DTSTART | Error | RFC 5545 |
| R12 | Inside a STANDARD/DAYLIGHT observance, RRULE UNTIL is not a UTC date-time | Error | RFC 5545 |
| X01 | RECURRENCE-ID override has no master component (same UID, no RECURRENCE-ID) in the same iCalendar object | Warning | Importer behaviour |
| O01 | TRANSP is not OPAQUE or TRANSPARENT | Error | RFC 5545 |
| O02 | PRIORITY is not an integer in 0–9 | Error | RFC 5545 |
| O03 | PERCENT-COMPLETE is not an integer in 0–100 | Error | RFC 5545 |
| O04 | SEQUENCE is not an integer | Error | RFC 5545 |
| O05 | GEO is not two semicolon-separated floats | Error | RFC 5545 |
| O06 | VALARM is missing a property its ACTION requires (or has exactly one of DURATION/REPEAT) | Error | RFC 5545 |
| O07 | VTODO carries both DUE and DURATION | Error | RFC 5545 |
| O08 | VALARM has an absolute (DATE-TIME) TRIGGER but its event/to-do lacks the DTSTART (or DTEND/DUE) it triggers on | Error | RFC 5545 |
| O09 | FREEBUSY period whose start is not before its end | Error | RFC 5545 |
| O10 | VALARM REPEAT value is not an integer | Error | RFC 5545 |
| W01 | Unescaped ';' or ',' inside a SUMMARY, DESCRIPTION or LOCATION value | Warning | RFC 5545 + importer behaviour |
| W02 | Backslash followed by a character outside the escape set (\\, \;, \,, \n, \N) | Warning | RFC 5545 |

Rule groups: **S** serialisation (raw bytes and content lines) ·
**C** VCALENDAR envelope · **V** required properties ·
**D** date/time values · **E** DTEND and DURATION · **T** TZID and
VTIMEZONE (presence and form only, never transitions) · **R** RRULE
(syntax and form cross-checks, never expansion) · **X**
recurrence-adjacent, importer-documented · **O** other typed values
and components · **W** TEXT escaping.

## Tests

```console
$ python3 run_tests.py
```

36 tests: one violating fixture per rule (67, each checked to fire
exactly its own rule at the designed severity), a valid corpus of
19 real-world-shaped files that must all produce zero findings,
anti-rule fixtures pinning the legal constructs listed under
*Honest limits*, regression fixtures for every defect the
independent code review found (including a 2000-level-deep
duplicate-timezone file that must produce findings, never a
traceback), and the CLI contract (exit codes, `--strict`,
JSON output, recursive folder scanning).

## License

MIT — see `LICENSE`.
