"""Core linting engine for icslint.

Implements the 67 rules of DESIGN.md exactly as designed: every rule
cites RFC 5545 (or a named, dated importer source), severities follow
the design's severity model, and a conforming file produces zero
findings. No recurrence expansion, no timezone-transition semantics:
everything is decided from the file alone.

Rule metadata lives in RULES: id -> (severity, source_type, source,
summary). source_type is one of "RFC 5545", "Importer behaviour",
"RFC 5545 + importer behaviour", "Robustness advice" — importer-
sourced findings are labelled as such in the output, never blended
silently with RFC citations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ERROR = "ERROR"
WARNING = "WARNING"

RFC = "RFC 5545"
IMP = "Importer behaviour"
BOTH = "RFC 5545 + importer behaviour"
ADV = "Robustness advice"

RULES = {
    # --- S: serialisation -------------------------------------------------
    "S01": (ERROR, BOTH, "RFC 5545 §3.1; importer behaviour: SpreadEvent, Apr 2026 (Outlook silently fails to import LF files); iCal Converter, Aug 2026",
            "Line ends with a bare LF instead of CRLF (or the final line has no CRLF at all)"),
    "S02": (ERROR, RFC, "RFC 5545 §3.1",
            "Line ends with a bare CR instead of CRLF"),
    "S03": (WARNING, BOTH, "RFC 5545 §3.1 (SHOULD NOT); importer behaviour: SpreadEvent / iCal Converter, 2026 (unfolded long lines break Outlook and Google parsing)",
            "Physical line longer than 75 octets, not folded"),
    "S04": (WARNING, ADV, "RFC 5545 §3.1 note (parsers must cope; generators are not forbidden — this is robustness advice, not a spec violation)",
            "Fold falls inside a multi-byte UTF-8 character; naive parsers garble it"),
    "S05": (ERROR, RFC, "RFC 5545 §3.1",
            "First line begins with a space or tab (a fold continuation with nothing to continue)"),
    "S06": (ERROR, RFC, "RFC 5545 §3.1 contentline ABNF",
            "Blank line inside the iCalendar object"),
    "S07": (ERROR, RFC, "RFC 5545 §3.1 contentline ABNF",
            "Content line has no ':' separating the property name from its value"),
    "S08": (ERROR, BOTH, "RFC 5545 §3.1.4 and §8 (MUST generate UTF-8); importer behaviour: csvtoics.app, Aug 2026 §11 (UTF-16 fails immediately); iCal Converter, Aug 2026",
            "File is not valid UTF-8"),
    "S09": (WARNING, IMP, "Importer behaviour: csvtoics.app, Aug 2026 §11 (a BOM is 'usually stripped')",
            "File starts with a UTF-8 byte-order mark"),
    "S10": (ERROR, RFC, "RFC 5545 §3.6–§3.6.6 component ABNFs and §3.7–§3.8 conformance ('MUST NOT occur more than once')",
            "A property that may occur at most once in its component occurs twice"),
    # --- C: VCALENDAR envelope --------------------------------------------
    "C01": (ERROR, BOTH, "RFC 5545 §3.4; importer behaviour: iCal Converter, Aug 2026 ('the first line must be BEGIN:VCALENDAR')",
            "Content outside a VCALENDAR object, or an object not opened/closed by BEGIN/END:VCALENDAR"),
    "C02": (ERROR, RFC, "RFC 5545 §3.4 icalobject ABNF; §3.6.1–§3.6.6 nesting rules",
            "Unclosed, mismatched or illegally nested BEGIN/END components"),
    "C03": (ERROR, RFC, "RFC 5545 §3.6 and §3.7.3",
            "VCALENDAR has no PRODID"),
    "C04": (ERROR, RFC, "RFC 5545 §3.6 and §3.7.4",
            "VCALENDAR has no VERSION"),
    "C05": (ERROR, BOTH, "RFC 5545 §3.7.4 ('2.0' corresponds to this memo); importer behaviour: SpreadEvent, Apr 2026 ('Always 2.0. Anything else and parsers will refuse the file')",
            "VERSION is not 2.0"),
    "C06": (ERROR, RFC, "RFC 5545 §3.6",
            "VCALENDAR contains no calendar component at all"),
    # --- V: required properties -------------------------------------------
    "V01": (ERROR, RFC, "RFC 5545 §3.6.1–§3.6.4 ABNFs; §3.8.4.7",
            "VEVENT/VTODO/VJOURNAL/VFREEBUSY has no UID (or an empty one)"),
    "V02": (ERROR, BOTH, "RFC 5545 §3.6.1–§3.6.4 ABNFs; §3.8.7.2; importer behaviour: Terence Eden, Jul 2026 (missing DTSTAMP is the documented cause of Google's 'Unable to launch event')",
            "VEVENT/VTODO/VJOURNAL/VFREEBUSY has no DTSTAMP"),
    "V03": (ERROR, BOTH, "RFC 5545 §3.6.1 and §3.8.2.4; importer behaviour: iCal Converter, Aug 2026 (Google silently rejects events lacking DTSTART)",
            "VEVENT has no DTSTART and the VCALENDAR specifies no METHOD"),
    "V04": (ERROR, BOTH, "RFC 5545 §3.8.4.7 and §3.8.4.4; importer behaviour: csvtoics.app, Aug 2026 §6 (Google treats a repeated UID as an update; Outlook may refuse)",
            "Two components share the same UID and the same RECURRENCE-ID"),
    "V05": (ERROR, RFC, "RFC 5545 §3.8.7.2 (also §3.8.7.1 CREATED, §3.8.7.3 LAST-MODIFIED)",
            "DTSTAMP (or CREATED / LAST-MODIFIED) is not in UTC form"),
    "V06": (ERROR, RFC, "RFC 5545 §3.6.2 todoprop ABNF comment",
            "VTODO carries a DURATION but no DTSTART"),
    "V07": (ERROR, RFC, "RFC 5545 §3.8.2.4, §3.8.2.2 and §3.8.2.6 (VFREEBUSY times)",
            "VFREEBUSY DTSTART, DTEND or FREEBUSY value is not in UTC form"),
    # --- D: date / date-time values ---------------------------------------
    "D01": (ERROR, BOTH, "RFC 5545 §3.3.4; importer behaviour: csvtoics.app, Aug 2026 §3 (rejects impossible dates such as 20260230)",
            "DATE value is malformed or impossible (e.g. 20260230)"),
    "D02": (ERROR, RFC, "RFC 5545 §3.3.5 (incorporating §3.3.4 and §3.3.12)",
            "DATE-TIME value is malformed (missing T, hyphen/colon separators, UTC-offset suffix, out-of-range fields)"),
    "D03": (ERROR, RFC, "RFC 5545 per-property ABNFs, e.g. §3.8.2.2/§3.8.2.4 ('Value MUST match value type')",
            "VALUE= parameter disagrees with the value's actual form"),
    "D04": (ERROR, RFC, "RFC 5545 §3.8.2.2, §3.8.2.3 and §3.8.4.4",
            "DTEND, DUE or RECURRENCE-ID has a different value kind (DATE vs DATE-TIME) from DTSTART"),
    "D05": (ERROR, RFC, "RFC 5545 §3.8.2.2, §3.8.2.3 and §3.8.4.4 ('local time if and only if DTSTART is local time')",
            "DTEND, DUE or RECURRENCE-ID is local where DTSTART is UTC, or UTC where DTSTART is local"),
    # --- E: DTEND and DURATION --------------------------------------------
    "E01": (ERROR, RFC, "RFC 5545 §3.6.1",
            "VEVENT carries both DTEND and DURATION"),
    "E02": (ERROR, BOTH, "RFC 5545 §3.8.2.2 (and §3.8.2.3 for DUE); importer behaviour: csvtoics.app, Aug 2026 §5 (equal all-day dates are a zero-length event some importers drop)",
            "DTEND (or DUE) is not later than DTSTART"),
    "E03": (ERROR, RFC, "RFC 5545 §3.3.6 dur-value ABNF",
            "DURATION value is malformed (including Y/M designators, which iCalendar does not support)"),
    "E04": (ERROR, RFC, "RFC 5545 §3.8.2.5 ('a positive duration of time')",
            "VEVENT/VTODO DURATION is negative or zero"),
    "E05": (ERROR, RFC, "RFC 5545 §3.8.2.5 and §3.6.1",
            "DTSTART is a DATE but DURATION is not a whole dur-day or dur-week value"),
    # --- T: TZID and VTIMEZONE --------------------------------------------
    "T01": (ERROR, RFC, "RFC 5545 §3.2.19; §3.3.5 Form #2",
            "TZID parameter applied to a UTC (Z) value"),
    "T02": (ERROR, RFC, "RFC 5545 §3.2.19",
            "TZID parameter applied to a DATE value"),
    "T03": (WARNING, BOTH, "RFC 5545 §3.2.19 and §3.6.5 (MUST) — warning because importer behaviour waives it: csvtoics.app, Aug 2026 §4 (the TZID must match a VTIMEZONE 'or the app must know the name'; IANA names resolve in the big importers)",
            "TZID referenced but no VTIMEZONE in the file defines it"),
    "T04": (ERROR, BOTH, "RFC 5545 §3.6.5; importer behaviour: csvtoics.app, Aug 2026 §4 ('Conflicting VTIMEZONE bodies for the same id are an error')",
            "Two VTIMEZONE components define the same TZID with different bodies"),
    "T05": (ERROR, RFC, "RFC 5545 §3.6.5",
            "VTIMEZONE has no TZID property"),
    "T06": (ERROR, RFC, "RFC 5545 §3.6.5",
            "VTIMEZONE has no STANDARD or DAYLIGHT sub-component"),
    "T07": (ERROR, RFC, "RFC 5545 §3.6.5",
            "STANDARD/DAYLIGHT is missing DTSTART, TZOFFSETFROM or TZOFFSETTO"),
    "T08": (ERROR, RFC, "RFC 5545 §3.6.5 and §3.8.2.4",
            "STANDARD/DAYLIGHT DTSTART is not a plain local time (carries a Z or a TZID)"),
    "T09": (ERROR, RFC, "RFC 5545 §3.3.14",
            "TZOFFSETFROM/TZOFFSETTO value is malformed (bad form, second = 60, or negative zero)"),
    # --- R: RRULE -----------------------------------------------------------
    "R01": (ERROR, RFC, "RFC 5545 §3.3.10 ('The FREQ rule part is REQUIRED')",
            "RRULE has no FREQ rule part"),
    "R02": (ERROR, BOTH, "RFC 5545 §3.3.10 freq ABNF; importer behaviour: csvtoics.app, Aug 2026 §12",
            "FREQ is not one of SECONDLY, MINUTELY, HOURLY, DAILY, WEEKLY, MONTHLY, YEARLY"),
    "R03": (ERROR, BOTH, "RFC 5545 §3.3.10 ('MUST NOT occur in the same recur'); importer behaviour: csvtoics.app, Aug 2026 §12",
            "RRULE carries both COUNT and UNTIL"),
    "R04": (ERROR, RFC, "RFC 5545 §3.3.10 ('Individual rule parts MUST only be specified once')",
            "The same rule part occurs twice in one RRULE"),
    "R05": (WARNING, BOTH, "RFC 5545 §3.3.10 recur ABNF (closed set); importer behaviour: csvtoics.app, Aug 2026 §12 ('Unknown parts are a warning')",
            "RRULE contains a rule part outside the ABNF set"),
    "R06": (ERROR, RFC, "RFC 5545 §3.3.10 ('UNTIL MUST have the same value type as DTSTART')",
            "UNTIL's value kind (DATE vs DATE-TIME) disagrees with DTSTART's"),
    "R07": (ERROR, BOTH, "RFC 5545 §3.3.10; importer behaviour: iCal Converter, Aug 2026 (Google drops or truncates series with this defect)",
            "UNTIL's UTC-ness disagrees with DTSTART's form (never applied inside STANDARD/DAYLIGHT — see R12)"),
    "R08": (ERROR, RFC, "RFC 5545 §3.3.10 (per-part ranges; weekday ABNF; WKST valid values; INTERVAL 'positive integer')",
            "A rule part's value is out of range, not a number, or not a valid weekday token"),
    "R09": (ERROR, RFC, "RFC 5545 §3.3.10 MUST NOTs and N/A table; BYSETPOS conjunction rule",
            "Forbidden rule-part/FREQ combination (e.g. BYMONTHDAY with FREQ=WEEKLY, BYSETPOS with no other BYxxx part)"),
    "R10": (WARNING, RFC, "RFC 5545 §3.6.1 ('SHOULD NOT occur more than once')",
            "Component carries more than one RRULE property"),
    "R11": (ERROR, RFC, "RFC 5545 §3.8.2.4",
            "Component carries an RRULE but no DTSTART"),
    "R12": (ERROR, RFC, "RFC 5545 §3.3.10 ('In STANDARD and DAYLIGHT sub-components the UNTIL rule part MUST always be specified as a date with UTC time')",
            "Inside a STANDARD/DAYLIGHT observance, RRULE UNTIL is not a UTC date-time"),
    # --- X: recurrence-adjacent --------------------------------------------
    "X01": (WARNING, IMP, "Importer behaviour: iCal Converter, Aug 2026 (orphan overrides are discarded by Google or turned into standalone events on the wrong date)",
            "RECURRENCE-ID override has no master component (same UID, no RECURRENCE-ID) in the same iCalendar object"),
    # --- O: other typed values and components -------------------------------
    "O01": (ERROR, RFC, "RFC 5545 §3.8.2.7 transvalue ABNF",
            "TRANSP is not OPAQUE or TRANSPARENT"),
    "O02": (ERROR, RFC, "RFC 5545 §3.8.1.9",
            "PRIORITY is not an integer in 0–9"),
    "O03": (ERROR, RFC, "RFC 5545 §3.8.1.8",
            "PERCENT-COMPLETE is not an integer in 0–100"),
    "O04": (ERROR, RFC, "RFC 5545 §3.8.7.4 (value type INTEGER)",
            "SEQUENCE is not an integer"),
    "O05": (ERROR, RFC, "RFC 5545 §3.8.1.6",
            "GEO is not two semicolon-separated floats"),
    "O06": (ERROR, RFC, "RFC 5545 §3.6.6",
            "VALARM is missing a property its ACTION requires (or has exactly one of DURATION/REPEAT)"),
    "O07": (ERROR, RFC, "RFC 5545 §3.6.2 todoprop ABNF",
            "VTODO carries both DUE and DURATION"),
    "O08": (ERROR, RFC, "RFC 5545 §3.6.6 (absolute TRIGGER presence rules)",
            "VALARM has an absolute (DATE-TIME) TRIGGER but its event/to-do lacks the DTSTART (or DTEND/DUE) it triggers on"),
    "O09": (ERROR, RFC, "RFC 5545 §3.3.9 ('The start MUST be before the end')",
            "FREEBUSY period whose start is not before its end"),
    "O10": (ERROR, RFC, "RFC 5545 §3.8.6.2 (value type INTEGER)",
            "VALARM REPEAT value is not an integer"),
    # --- W: TEXT escaping ----------------------------------------------------
    "W01": (WARNING, BOTH, "RFC 5545 §3.3.11 (MUST be escaped); importer behaviour: SpreadEvent, Apr 2026 (Outlook truncates the value at an unescaped semicolon)",
            "Unescaped ';' or ',' inside a SUMMARY, DESCRIPTION or LOCATION value"),
    "W02": (WARNING, RFC, "RFC 5545 §3.3.11 ESCAPED-CHAR ABNF; 'a COLON … SHALL NOT be escaped'",
            "Backslash followed by a character outside the escape set (\\\\, \\;, \\,, \\n, \\N)"),
}


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    severity: str
    component: str
    message: str
    source: str
    source_type: str

    def sort_key(self):
        return (self.file, self.line, self.rule, self.message)


@dataclass
class Prop:
    name: str            # upper-cased property name
    params: dict         # upper-cased param name -> list of values (unquoted)
    value: str           # raw value text
    line: int            # physical line where the content line starts


@dataclass
class Component:
    name: str            # upper-cased component name
    line: int            # physical line of BEGIN
    end_line: int = 0    # physical line of END (or last line if unclosed)
    props: list = field(default_factory=list)
    children: list = field(default_factory=list)
    parent: object = None

    def get(self, name):
        for p in self.props:
            if p.name == name:
                return p
        return None

    def getall(self, name):
        return [p for p in self.props if p.name == name]

    def has(self, name):
        return self.get(name) is not None

    def label(self):
        uid = self.get("UID")
        if uid is not None and uid.value.strip():
            uid_text = uid.value.strip()
            if len(uid_text) > 40:
                uid_text = uid_text[:40] + "…"
            return f"{self.name}[UID={uid_text}]"
        return self.name


# --------------------------------------------------------------------------
# Physical lines (bytes) — S01/S02/S03/S04/S05/S06 work at this level.
# --------------------------------------------------------------------------

def _split_physical(data: bytes):
    """Split raw bytes into physical lines.

    Returns a list of (content_bytes, ending) where ending is one of
    'CRLF', 'LF', 'CR', 'NONE' (unterminated final line).
    """
    lines = []
    start = 0
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == 0x0D:  # CR
            if i + 1 < n and data[i + 1] == 0x0A:
                lines.append((data[start:i], "CRLF"))
                i += 2
            else:
                lines.append((data[start:i], "CR"))
                i += 1
            start = i
        elif b == 0x0A:  # LF not preceded by CR
            lines.append((data[start:i], "LF"))
            i += 1
            start = i
        else:
            i += 1
    if start < n:
        lines.append((data[start:n], "NONE"))
    return lines


def _ends_mid_utf8(b: bytes) -> bool:
    """True if b ends in the middle of a multi-byte UTF-8 sequence."""
    if not b:
        return False
    j = len(b) - 1
    while j >= 0 and 0x80 <= b[j] <= 0xBF:
        j -= 1
    if j < 0:
        return False
    lead = b[j]
    if lead < 0x80:
        return False
    if 0xC0 <= lead <= 0xDF:
        need = 2
    elif 0xE0 <= lead <= 0xEF:
        need = 3
    elif 0xF0 <= lead <= 0xF7:
        need = 4
    else:
        return False
    return (len(b) - j) < need


# --------------------------------------------------------------------------
# Content lines — unfolding and parsing.
# --------------------------------------------------------------------------

def _split_unquoted(text: str, sep: str):
    """Split on sep, ignoring separators inside double quotes."""
    parts = []
    buf = []
    in_q = False
    for ch in text:
        if ch == '"':
            in_q = not in_q
            buf.append(ch)
        elif ch == sep and not in_q:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _parse_content_line(text: str):
    """Parse an unfolded content line.

    Returns (name, params, value) or None if there is no ':' outside
    quoted parameter values (an S07 line).
    """
    in_q = False
    colon = -1
    for idx, ch in enumerate(text):
        if ch == '"':
            in_q = not in_q
        elif ch == ":" and not in_q:
            colon = idx
            break
    if colon < 0:
        return None
    head, value = text[:colon], text[colon + 1:]
    parts = _split_unquoted(head, ";")
    name = parts[0].strip().upper()
    # RFC 5545 §3.1: contentline = [group "."] name — a group prefix
    # (e.g. "home.DTSTART") is not part of the property name, and a
    # grouped DTSTART *is* a DTSTART. Strip the prefix so every rule
    # sees the bare name.
    if "." in name:
        group, _dot, rest = name.partition(".")
        if rest and re.fullmatch(r"[A-Z0-9-]+", group):
            name = rest
    params = {}
    for part in parts[1:]:
        if "=" in part:
            pname, pval = part.split("=", 1)
            vals = []
            for v in _split_unquoted(pval, ","):
                v = v.strip()
                if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                vals.append(v)
            params.setdefault(pname.strip().upper(), []).extend(vals)
        elif part.strip():
            params.setdefault(part.strip().upper(), [])
    return name, params, value


# --------------------------------------------------------------------------
# Date / time / duration value helpers.
# --------------------------------------------------------------------------

_DATE_SHAPE = re.compile(r"^\d{8}$")
_DT_SHAPE = re.compile(r"^(\d{8})[Tt](\d{6})([Zz])?$")
_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
        return 29 if leap else 28
    if month in (4, 6, 9, 11):
        return 30
    return 31


def _valid_date(s: str) -> bool:
    """s matches \\d{8}; check month/day plausibility (leap-aware)."""
    year, month, day = int(s[:4]), int(s[4:6]), int(s[6:8])
    if not 1 <= month <= 12:
        return False
    return 1 <= day <= _days_in_month(year, month)


def _parse_datetime(s: str):
    """Parse a DATE-TIME value. Returns ((y,m,d,H,M,S), is_utc) or None."""
    m = _DT_SHAPE.match(s)
    if not m:
        return None
    date_part, time_part, z = m.group(1), s[9:15], m.group(3)
    if not _valid_date(date_part):
        return None
    hh, mm, ss = int(time_part[:2]), int(time_part[2:4]), int(time_part[4:6])
    if hh > 23 or mm > 59 or ss > 60:
        return None
    tup = (int(date_part[:4]), int(date_part[4:6]), int(date_part[6:8]), hh, mm, ss)
    return tup, bool(z)


def _shape_kind(value: str):
    """'DATE', 'DATETIME' or None, judged from the value's shape alone."""
    if _DATE_SHAPE.match(value):
        return "DATE"
    if len(value) > 8 and value[8] in "Tt":
        return "DATETIME"
    return None


def _value_param(prop: Prop):
    vals = prop.params.get("VALUE")
    if vals:
        return vals[0].upper()
    return None


def _tzid_param(prop: Prop):
    vals = prop.params.get("TZID")
    if vals:
        return vals[0]
    return None


def _canon_kind(token):
    """Canonical kind token for a shape or VALUE= parameter value:
    'DATE' or 'DATETIME', else None. The VALUE= spelling is
    'DATE-TIME' while the internal shape token is 'DATETIME' —
    comparing them raw makes every explicit VALUE=DATE-TIME look
    like a mismatch (the F1 false positive)."""
    if token == "DATE":
        return "DATE"
    if token in ("DATETIME", "DATE-TIME"):
        return "DATETIME"
    return None


def _effective_kind(prop: Prop):
    """The value's kind for cross-checks: its shape if determinable
    (a VALUE= parameter that disagrees with the shape is D03's
    defect, already reported), else the VALUE= parameter. Always
    a canonical token ('DATE' / 'DATETIME' / None)."""
    shape = _shape_kind(prop.value.strip())
    if shape is not None:
        return shape
    return _canon_kind(_value_param(prop))


# Duration grammar, RFC 5545 §3.3.6:
#   dur-value = (["+"] / "-") "P" (dur-week / dur-date / dur-time)
#   dur-week  = 1*DIGIT "W"
#   dur-date  = dur-day [dur-time]        dur-day  = 1*DIGIT "D"
#   dur-time  = "T" (dur-hour [dur-minute [dur-second]] /
#                    dur-minute [dur-second] / dur-second)
_DUR_RE = re.compile(
    r"^([+-])?P(?:(\d+)W|(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?)$"
)


def _parse_duration(value: str):
    """Parse a DURATION value.

    Returns (total_sign, is_pure_day_or_week, seconds_approx) or None if
    the value does not match the §3.3.6 grammar. seconds_approx is None
    for week values (not needed by any rule).
    """
    m = _DUR_RE.match(value.strip().upper())
    if not m:
        return None
    sign, weeks, days, hours, minutes, seconds = m.groups()
    if weeks is None and days is None and hours is None and minutes is None and seconds is None:
        return None  # bare "P" or "PT"
    if ("T" in value.upper()) and hours is None and minutes is None and seconds is None:
        return None  # "P1DT" — T with no time components
    pure = False
    if weeks is not None:
        pure = True
        total = int(weeks) * 604800
    elif days is not None and hours is None and minutes is None and seconds is None:
        pure = True
        total = int(days) * 86400
    else:
        total = (int(days or 0) * 86400 + int(hours or 0) * 3600
                 + int(minutes or 0) * 60 + int(seconds or 0))
    if sign == "-" and total is not None:
        total = -total
    return (sign, pure, total)


def _is_zero_or_negative_duration(value: str) -> bool:
    parsed = _parse_duration(value)
    if parsed is None:
        return False
    sign, _pure, total = parsed
    if sign == "-":
        return True
    return total is not None and total <= 0




# --------------------------------------------------------------------------
# The linter.
# --------------------------------------------------------------------------

_KNOWN_COMPONENTS = {
    "VCALENDAR", "VEVENT", "VTODO", "VJOURNAL", "VFREEBUSY",
    "VTIMEZONE", "STANDARD", "DAYLIGHT", "VALARM",
}

_EVENT_LIKE = ("VEVENT", "VTODO", "VJOURNAL", "VFREEBUSY")

_SINGLETONS = {
    "VCALENDAR": {"PRODID", "VERSION", "CALSCALE", "METHOD"},
    "VEVENT": {"DTSTAMP", "UID", "DTSTART", "CLASS", "CREATED", "DESCRIPTION",
               "GEO", "LAST-MODIFIED", "LOCATION", "ORGANIZER", "PRIORITY",
               "SEQUENCE", "STATUS", "SUMMARY", "TRANSP", "URL",
               "RECURRENCE-ID", "DTEND", "DURATION"},
    "VTODO": {"DTSTAMP", "UID", "CLASS", "COMPLETED", "CREATED", "DESCRIPTION",
              "DTSTART", "GEO", "LAST-MODIFIED", "LOCATION", "ORGANIZER",
              "PERCENT-COMPLETE", "PRIORITY", "RECURRENCE-ID", "SEQUENCE",
              "STATUS", "SUMMARY", "URL", "DUE", "DURATION"},
    "VJOURNAL": {"DTSTAMP", "UID", "CLASS", "CREATED", "DESCRIPTION", "DTSTART",
                 "LAST-MODIFIED", "ORGANIZER", "RECURRENCE-ID", "SEQUENCE",
                 "STATUS", "SUMMARY", "URL"},
    "VFREEBUSY": {"DTSTAMP", "UID", "DTSTART", "DTEND", "ORGANIZER", "URL"},
    "VTIMEZONE": {"TZID", "LAST-MODIFIED", "TZURL"},
    "STANDARD": {"DTSTART", "TZOFFSETFROM", "TZOFFSETTO"},
    "DAYLIGHT": {"DTSTART", "TZOFFSETFROM", "TZOFFSETTO"},
    "VALARM": {"ACTION", "TRIGGER", "DURATION", "REPEAT", "DESCRIPTION",
               "SUMMARY"},
}

# Properties whose values are DATE / DATE-TIME (D-section checks).
_TEMPORAL_SINGLE = {
    "DTSTART", "DTEND", "DUE", "DTSTAMP", "CREATED", "LAST-MODIFIED",
    "COMPLETED", "RECURRENCE-ID",
}
_TEMPORAL_LIST = {"EXDATE", "RDATE"}
_ALWAYS_DATETIME = {"DTSTAMP", "CREATED", "LAST-MODIFIED", "COMPLETED"}


class _Linter:
    def __init__(self, filename: str):
        self.file = filename
        self.findings = []
        self.nodes = []        # every component, in BEGIN order
        self.objects = []      # VCALENDAR components
        self.last_line = 0

    def add(self, line, rule, component, message):
        severity, source_type, source, _summary = RULES[rule]
        self.findings.append(Finding(
            file=self.file, line=line, rule=rule, severity=severity,
            component=component, message=message,
            source=source, source_type=source_type))

    # -- containment label for line-level (S) findings ----------------------
    def label_for_line(self, line):
        best = None
        for node in self.nodes:
            if node.line <= line <= (node.end_line or self.last_line):
                if best is None or node.line >= best.line:
                    best = node
        if best is None:
            return "-"
        return best.label()

    # -- main entry ----------------------------------------------------------
    def run(self, data: bytes):
        # S09: BOM is stripped before all other checks.
        bom = data.startswith(b"\xef\xbb\xbf")
        if bom:
            data = data[3:]
        # S08, NUL form: a NUL byte can never appear in a UTF-8
        # iCalendar stream. This is the mechanism DESIGN S08 states
        # — UTF-16 files "fail on the first NUL": BOM-less UTF-16
        # of ASCII content is byte-wise valid UTF-8 apart from its
        # NULs, and a lone NUL inside a value is just as invalid.
        # Nothing else can be decided from such a file, so S08 is
        # reported alone.
        if b"\x00" in data:
            if bom:
                self.add(1, "S09", "-",
                         "File starts with a UTF-8 byte-order mark (BOM). "
                         "Most importers strip it, but it does not belong in the file.")
            self.add(1, "S08", "-",
                     "File contains a NUL byte, so it is not a UTF-8 "
                     "iCalendar stream (this is how UTF-16 exports fail — "
                     "on the first NUL). iCalendar streams must be "
                     "generated in the UTF-8 charset.")
            return self.findings
        physical = _split_physical(data)
        self.last_line = max(1, len(physical))

        # Unfold into logical lines at the byte level first: a fold
        # that splits a multi-byte UTF-8 character (S04) makes the
        # raw stream undecodable as a flat sequence, while the
        # unfolded logical lines decode fine.
        logical_bytes = []  # (start_physical_line, bytes)
        cur = None          # [start_line, bytearray]
        for idx, (content, _ending) in enumerate(physical):
            lineno = idx + 1
            if content[:1] in (b" ", b"\t") and cur is not None:
                cur[1].extend(content[1:])
            else:
                if cur is not None:
                    logical_bytes.append(cur)
                start = content
                if content[:1] in (b" ", b"\t"):
                    start = content[1:]  # orphan continuation (S05 below)
                cur = [lineno, bytearray(start)]
        if cur is not None:
            logical_bytes.append(cur)

        # S08: the (unfolded) stream must be valid UTF-8. If it is
        # not, nothing else can be decided from it.
        logical = []
        try:
            logical = [(ln, bytes(b).decode("utf-8"))
                       for ln, b in logical_bytes]
        except UnicodeDecodeError:
            if bom:
                self.add(1, "S09", "-",
                         "File starts with a UTF-8 byte-order mark (BOM). "
                         "Most importers strip it, but it does not belong in the file.")
            self.add(1, "S08", "-",
                     "File is not valid UTF-8 (UTF-16 exports fail the same way). "
                     "iCalendar streams must be generated in the UTF-8 charset.")
            return self.findings
        if bom:
            self.add(1, "S09", None,
                     "File starts with a UTF-8 byte-order mark (BOM). "
                     "Most importers strip it, but it does not belong in the file.")

        # S01 / S02 / S03 / S05 / S06 at the physical-line level.
        for idx, (content, ending) in enumerate(physical):
            lineno = idx + 1
            if ending == "LF":
                self.add(lineno, "S01", None,
                         "Line ends with a bare LF. Content lines must end with CRLF.")
            elif ending == "NONE":
                self.add(lineno, "S01", None,
                         "Final line has no CRLF terminator. Every content line, "
                         "including the last, must end with CRLF.")
            elif ending == "CR":
                self.add(lineno, "S02", None,
                         "Line ends with a bare CR. Content lines must end with CRLF.")
            if len(content) > 75:
                self.add(lineno, "S03", None,
                         f"Line is {len(content)} octets long. Lines should not be "
                         "longer than 75 octets; longer lines should be folded.")
            if idx == 0 and content[:1] in (b" ", b"\t"):
                self.add(lineno, "S05", None,
                         "The first line begins with a space/tab — a fold "
                         "continuation with no line before it to continue.")
            if len(content) == 0:
                self.add(lineno, "S06", None,
                         "Blank line. Every line in an iCalendar object must be "
                         "a content line (name;params:value).")
            # S04: this line is a continuation and the previous line's
            # content ends mid-UTF-8-sequence.
            if idx > 0 and content[:1] in (b" ", b"\t"):
                if _ends_mid_utf8(physical[idx - 1][0]):
                    self.add(lineno, "S04", None,
                             "This fold splits a multi-byte UTF-8 character across "
                             "two lines. A conforming parser copes, but parsers that "
                             "unfold naively will garble the character.")

        # Parse content lines; S07 for lines with no colon.
        records = []  # (line, name, params, value)
        for lineno, text in logical:
            if text == "":
                continue  # blank line: S06 already fired
            parsed = _parse_content_line(text)
            if parsed is None:
                self.add(lineno, "S07", None,
                         "Content line has no ':' separating the property name "
                         f"from its value: {text[:60]!r}")
                continue
            name, params, value = parsed
            records.append((lineno, name, params, value))

        self._build_tree(records)
        # Resolve deferred component labels for line-level findings.
        for f in self.findings:
            if f.component is None:
                f.component = self.label_for_line(f.line)

        self._check_objects()
        for obj in self.objects:
            self._check_t04(obj)
        for node in self.nodes:
            self._check_singletons(node)
            self._check_component(node)
        self._check_v04()
        self._check_t03()
        self._check_x01()
        self.findings.sort(key=lambda f: (f.line, f.rule, f.message))
        return self.findings

    # -- tree building: C01 / C02 -------------------------------------------
    def _illegal_nesting(self, parent_name, child):
        if parent_name is None:
            return False  # top-level non-VCALENDAR is C01, not C02
        if parent_name in ("STANDARD", "DAYLIGHT", "VALARM"):
            return True   # these contain no sub-components at all
        if child == "VCALENDAR":
            return True
        if parent_name == "VCALENDAR":
            return child in ("STANDARD", "DAYLIGHT", "VALARM")
        if parent_name == "VTIMEZONE":
            return child in ("VEVENT", "VTODO", "VJOURNAL", "VFREEBUSY",
                             "VTIMEZONE", "VALARM")
        if parent_name in ("VEVENT", "VTODO"):
            return child in _KNOWN_COMPONENTS and child != "VALARM"
        if parent_name in ("VJOURNAL", "VFREEBUSY"):
            return child in _KNOWN_COMPONENTS
        return False  # unknown parent component: lenient

    def _build_tree(self, records):
        stack = []
        saw_object = False
        for lineno, name, params, value in records:
            if name == "BEGIN":
                comp_name = value.strip().upper()
                node = Component(name=comp_name, line=lineno,
                                 parent=stack[-1] if stack else None)
                if stack:
                    if self._illegal_nesting(stack[-1].name, comp_name):
                        self.add(lineno, "C02", node.label(),
                                 f"{comp_name} is nested inside {stack[-1].name}, "
                                 "where it cannot appear.")
                    stack[-1].children.append(node)
                else:
                    if comp_name != "VCALENDAR":
                        self.add(lineno, "C01", node.label(),
                                 f"Component {comp_name} sits outside any "
                                 "VCALENDAR object.")
                    else:
                        saw_object = True
                        self.objects.append(node)
                self.nodes.append(node)
                stack.append(node)
            elif name == "END":
                comp_name = value.strip().upper()
                if not stack:
                    self.add(lineno, "C02", comp_name or "-",
                             f"END:{comp_name} closes nothing — there is no "
                             "open component.")
                elif stack[-1].name == comp_name:
                    stack[-1].end_line = lineno
                    stack.pop()
                else:
                    self.add(lineno, "C02", stack[-1].label(),
                             f"END:{comp_name} does not match the open "
                             f"{stack[-1].name} component.")
                    # Recovery: pop up to and including a matching BEGIN.
                    names = [n.name for n in stack]
                    if comp_name in names:
                        idx = len(names) - 1 - names[::-1].index(comp_name)
                        while len(stack) > idx:
                            stack[-1].end_line = lineno
                            stack.pop()
            else:
                prop = Prop(name=name, params=params, value=value, line=lineno)
                if stack:
                    stack[-1].props.append(prop)
                else:
                    self.add(lineno, "C01", "-",
                             f"Content line {name} sits outside any VCALENDAR "
                             "object. The first line of an object must be "
                             "BEGIN:VCALENDAR and the last END:VCALENDAR.")
        for node in stack:
            node.end_line = self.last_line
            self.add(node.line, "C02", node.label(),
                     f"BEGIN:{node.name} is never closed by a matching "
                     f"END:{node.name}.")
        if not saw_object and not records:
            self.add(1, "C01", "-",
                     "File contains no VCALENDAR object at all.")

    # -- C03–C06 per VCALENDAR object ----------------------------------------
    def _check_objects(self):
        for obj in self.objects:
            label = "VCALENDAR"
            if not obj.has("PRODID"):
                self.add(obj.line, "C03", label,
                         "VCALENDAR has no PRODID property. Every iCalendar "
                         "object must include one.")
            version = obj.get("VERSION")
            if version is None:
                self.add(obj.line, "C04", label,
                         "VCALENDAR has no VERSION property. Every iCalendar "
                         "object must include one.")
            else:
                v = version.value.strip()
                ok = v == "2.0"
                if not ok and ";" in v:
                    parts = [p.strip() for p in v.split(";")]
                    ok = len(parts) == 2 and parts[1] == "2.0"
                if not ok:
                    self.add(version.line, "C05", label,
                             f"VERSION is {v!r}, not '2.0'. This memo defines "
                             "version 2.0; other values belong to other formats "
                             "and parsers refuse them.")
            if not obj.children:
                self.add(obj.line, "C06", label,
                         "VCALENDAR contains no calendar component. An object "
                         "must include at least one (VEVENT, VTODO, …).")

    # -- S10 ------------------------------------------------------------------
    def _check_singletons(self, node: Component):
        allowed = _SINGLETONS.get(node.name)
        if not allowed:
            return
        seen = {}
        for prop in node.props:
            if prop.name in allowed:
                if prop.name in seen:
                    self.add(prop.line, "S10", node.label(),
                             f"{prop.name} occurs more than once in this "
                             f"{node.name}. It must not occur more than once.")
                else:
                    seen[prop.name] = prop

    # -- per-component dispatch ------------------------------------------------
    def _check_component(self, node: Component):
        for prop in node.props:
            self._check_temporal_prop(node, prop)
            self._check_tzid_param(node, prop)
            self._check_text_prop(node, prop)
            self._check_simple_typed(node, prop)
            if prop.name == "RRULE":
                self._check_rrule(node, prop)
            if prop.name == "DURATION" and node.name in ("VEVENT", "VTODO"):
                self._check_duration_prop(node, prop)
            elif prop.name == "DURATION":
                # E03's grammar applies to the DURATION property
                # wherever it appears — VALARM included. (The E04/E05
                # checks in _check_duration_prop stay scoped to
                # VEVENT/VTODO, as designed.)
                self._check_duration_grammar(node, prop)
            if prop.name == "TRIGGER":
                self._check_trigger(node, prop)
            if prop.name in ("TZOFFSETFROM", "TZOFFSETTO"):
                self._check_utcoffset(node, prop)
        if node.name in _EVENT_LIKE:
            self._check_required(node)
        if node.name == "VEVENT":
            self._check_vevent(node)
        if node.name == "VTODO":
            self._check_vtodo(node)
        if node.name == "VFREEBUSY":
            self._check_vfreebusy(node)
        if node.name == "VTIMEZONE":
            self._check_vtimezone(node)
        if node.name in ("STANDARD", "DAYLIGHT"):
            self._check_observance(node)
        if node.name == "VALARM":
            self._check_valarm(node)
        # DTSTART-relative cross-checks (D04 / D05 / E02).
        self._check_dtstart_relatives(node)
        # R10 / R11 are per-component RRULE checks.
        rrules = node.getall("RRULE")
        if rrules:
            if not node.has("DTSTART"):
                self.add(rrules[0].line, "R11", node.label(),
                         "This component has an RRULE but no DTSTART. DTSTART "
                         "is required in every recurring component.")
            for extra in rrules[1:]:
                self.add(extra.line, "R10", node.label(),
                         "This component carries more than one RRULE property. "
                         "RRULE should not occur more than once.")


    # -- D01/D02/D03: temporal value validation -------------------------------
    def _validate_temporal(self, node, prop, value, line):
        """Validate one DATE/DATE-TIME value; fire D01/D02/D03 as needed.

        Returns the value's kind ('DATE'/'DATETIME'/None) judged from
        its shape, for use by cross-checks.
        """
        v = value.strip()
        vparam = _value_param(prop)
        shape = _shape_kind(v)
        declared = _canon_kind(vparam)
        if declared is not None and shape is not None and shape != declared:
            self.add(line, "D03", node.label(),
                     f"{prop.name} declares VALUE={vparam} but the value "
                     f"{v!r} is in "
                     f"{'DATE-TIME' if shape == 'DATETIME' else 'DATE'} "
                     "form. The value must match the declared value type.")
            return shape
        if declared is not None:
            expected = declared
        elif shape is not None:
            expected = shape
        elif prop.name in _ALWAYS_DATETIME or "T" in v or "t" in v:
            expected = "DATETIME"
        else:
            expected = "DATE"
        if expected == "DATE":
            if not (_DATE_SHAPE.match(v) and _valid_date(v)):
                self.add(line, "D01", node.label(),
                         f"{prop.name} value {v!r} is not a valid DATE. Dates "
                         "must be exactly YYYYMMDD and the day must exist in "
                         "that month (20260230 does not).")
        else:
            if _parse_datetime(v) is None:
                self.add(line, "D02", node.label(),
                         f"{prop.name} value {v!r} is not a valid DATE-TIME. "
                         "Date-times must be YYYYMMDDTHHMMSS with an optional "
                         "trailing Z — no hyphens, no colons, no UTC-offset "
                         "suffix — with hour 00–23, minute 00–59, second 00–60.")
        return shape

    def _check_temporal_prop(self, node, prop):
        name = prop.name
        if name in _TEMPORAL_SINGLE:
            kind = self._validate_temporal(node, prop, prop.value, prop.line)
            # V05: DTSTAMP / CREATED / LAST-MODIFIED must be UTC.
            if name in ("DTSTAMP", "CREATED", "LAST-MODIFIED"):
                v = prop.value.strip()
                if not (_shape_kind(v) == "DATETIME" and v[-1:] in "Zz"):
                    self.add(prop.line, "V05", node.label(),
                             f"{name} value {v!r} is not in UTC form. It must "
                             "be a date-time ending in 'Z'.")
            return kind
        if name in _TEMPORAL_LIST:
            vparam = _value_param(prop)
            if name == "RDATE" and vparam == "PERIOD":
                for period in prop.value.split(","):
                    self._validate_period(node, prop, period.strip(), prop.line)
                return None
            if vparam not in (None, "DATE", "DATE-TIME"):
                return None
            for item in prop.value.split(","):
                self._validate_temporal(node, prop, item, prop.line)
            return None
        if name == "FREEBUSY":
            for period in prop.value.split(","):
                self._validate_period(node, prop, period.strip(), prop.line)
            return None
        return None

    def _validate_period(self, node, prop, period, line):
        """Validate the date-times inside one PERIOD value (D02)."""
        if "/" not in period:
            self.add(line, "D02", node.label(),
                     f"{prop.name} value {period!r} is not a period. A period "
                     "is start/end or start/duration, separated by '/'.")
            return
        start, _sep, end = period.partition("/")
        if _parse_datetime(start.strip()) is None:
            self.add(line, "D02", node.label(),
                     f"{prop.name} period start {start.strip()!r} is not a "
                     "valid DATE-TIME (YYYYMMDDTHHMMSS, optional Z).")
        end = end.strip()
        if end and (end[0].isdigit()):
            if _parse_datetime(end) is None:
                self.add(line, "D02", node.label(),
                         f"{prop.name} period end {end!r} is not a valid "
                         "DATE-TIME (YYYYMMDDTHHMMSS, optional Z).")
        # A duration end is judged by the O09 pass (E03/E04 grammar).

    # -- T01/T02/T03: TZID parameters ------------------------------------------
    def _check_tzid_param(self, node, prop):
        tzid = _tzid_param(prop)
        if tzid is None:
            return
        if prop.name not in _TEMPORAL_SINGLE and prop.name not in _TEMPORAL_LIST:
            return
        v = prop.value.strip()
        kind = _effective_kind(prop)
        if kind == "DATE":
            self.add(prop.line, "T02", node.label(),
                     f"{prop.name} carries a TZID parameter but its value is a "
                     "DATE. TZID must not be applied to DATE properties.")
        elif kind == "DATETIME" and v[-1:] in "Zz":
            self.add(prop.line, "T01", node.label(),
                     f"{prop.name} carries a TZID parameter but its value is "
                     "in UTC form (trailing Z). TZID must not be applied to "
                     "UTC time values.")

    def _check_t03(self):
        defined = set()
        for node in self.nodes:
            if node.name == "VTIMEZONE":
                tz = node.get("TZID")
                if tz is not None:
                    defined.add(tz.value.strip())
        for node in self.nodes:
            for prop in node.props:
                if prop.name not in _TEMPORAL_SINGLE and prop.name not in _TEMPORAL_LIST:
                    continue
                tzid = _tzid_param(prop)
                if tzid is not None and tzid not in defined:
                    self.add(prop.line, "T03", node.label(),
                             f"TZID {tzid!r} is referenced here but the file "
                             "contains no VTIMEZONE defining it. Importers "
                             "that know the IANA name will still resolve it; "
                             "those that do not, will not.")

    # -- W01/W02: TEXT escaping --------------------------------------------------
    def _check_text_prop(self, node, prop):
        if prop.name not in ("SUMMARY", "DESCRIPTION", "LOCATION"):
            return
        v = prop.value
        i = 0
        w01_done = False
        w02_done = False
        while i < len(v):
            ch = v[i]
            if ch == "\\":
                nxt = v[i + 1] if i + 1 < len(v) else ""
                if nxt in ("\\", ";", ",", "n", "N"):
                    i += 2
                    continue
                if not w02_done:
                    self.add(prop.line, "W02", node.label(),
                             f"{prop.name} contains a backslash escape "
                             f"'\\{nxt}' that is not in the TEXT escape set "
                             "(\\\\, \\;, \\,, \\n, \\N). A colon in particular "
                             "must not be escaped.")
                    w02_done = True
                i += 2 if nxt else 1
                continue
            if ch in ";," and not w01_done:
                self.add(prop.line, "W01", node.label(),
                         f"{prop.name} contains an unescaped '{ch}'. In a "
                         "TEXT value, ';' and ',' must be escaped with a "
                         "backslash — Outlook truncates the value at an "
                         "unescaped semicolon.")
                w01_done = True
            i += 1

    # -- O01–O05: simple typed values ---------------------------------------------
    def _check_simple_typed(self, node, prop):
        v = prop.value.strip()
        if prop.name == "TRANSP":
            if v.upper() not in ("OPAQUE", "TRANSPARENT"):
                self.add(prop.line, "O01", node.label(),
                         f"TRANSP value {v!r} is not OPAQUE or TRANSPARENT — "
                         "those are the only two values the spec allows.")
        elif prop.name == "PRIORITY":
            if not _INT.match(v) or not 0 <= int(v) <= 9:
                self.add(prop.line, "O02", node.label(),
                         f"PRIORITY value {v!r} is not an integer in the "
                         "range 0–9.")
        elif prop.name == "PERCENT-COMPLETE":
            if not _INT.match(v) or not 0 <= int(v) <= 100:
                self.add(prop.line, "O03", node.label(),
                         f"PERCENT-COMPLETE value {v!r} is not an integer "
                         "in the range 0–100.")
        elif prop.name == "SEQUENCE":
            if not _INT.match(v):
                self.add(prop.line, "O04", node.label(),
                         f"SEQUENCE value {v!r} is not an integer.")
        elif prop.name == "GEO":
            parts = v.split(";")
            ok = len(parts) == 2 and all(_FLOAT.match(p.strip()) for p in parts)
            if not ok:
                self.add(prop.line, "O05", node.label(),
                         f"GEO value {v!r} is not two semicolon-separated "
                         "numbers (latitude;longitude).")

    # -- T09: UTC offsets ------------------------------------------------------------
    _UTCOFF_RE = re.compile(r"^([+-])(\d{2})(\d{2})(\d{2})?$")

    def _check_utcoffset(self, node, prop):
        v = prop.value.strip()
        m = self._UTCOFF_RE.match(v)
        bad = False
        if not m:
            bad = True
        else:
            sign, hh, mm, ss = m.groups()
            if int(hh) > 23 or int(mm) > 59 or (ss is not None and int(ss) > 59):
                bad = True
            if sign == "-" and int(hh) == 0 and int(mm) == 0 and (ss is None or int(ss) == 0):
                bad = True  # -0000 / -000000 are not allowed
        if bad:
            self.add(prop.line, "T09", node.label(),
                     f"{prop.name} value {v!r} is not a valid UTC offset. It "
                     "must be a sign followed by HHMM (optionally SS), the "
                     "seconds must not be 60, and -0000 is not allowed.")

    # -- E03/E04/E05: DURATION property ------------------------------------------------
    def _check_duration_grammar(self, node, prop):
        """E03 for a DURATION property in any component. Returns the
        parsed duration, or None (having fired E03)."""
        v = prop.value.strip()
        parsed = _parse_duration(v)
        if parsed is None:
            self.add(prop.line, "E03", node.label(),
                     f"DURATION value {v!r} does not match the duration "
                     "grammar (e.g. P1D, PT2H30M, P1W). Year and month "
                     "designators (Y, M after P) are not supported in "
                     "iCalendar durations.")
        return parsed

    def _check_duration_prop(self, node, prop):
        v = prop.value.strip()
        parsed = self._check_duration_grammar(node, prop)
        if parsed is None:
            return
        if _is_zero_or_negative_duration(v):
            self.add(prop.line, "E04", node.label(),
                     f"DURATION value {v!r} is not positive. A component's "
                     "duration must be a positive duration of time.")
        dtstart = node.get("DTSTART")
        if dtstart is not None:
            kind = _effective_kind(dtstart)
            if kind == "DATE" and not parsed[1]:
                self.add(prop.line, "E05", node.label(),
                         f"DTSTART is a DATE, so DURATION must be a whole "
                         f"dur-day (e.g. P1D) or dur-week (e.g. P1W) value; "
                         f"{v!r} has a time part or is not day/week shaped.")

    def _check_trigger(self, node, prop):
        # TRIGGER's default value type is DURATION; a malformed duration
        # value is an E03 defect. (Negative durations are normal here —
        # alarms usually fire before the event — so E04 never applies.)
        # With VALUE=DATE-TIME the trigger is an absolute date-time and
        # joins the D-section's property list: a malformed or
        # impossible one is a D02 defect.
        vparam = _value_param(prop)
        if vparam == "DATE-TIME":
            v = prop.value.strip()
            if _parse_datetime(v) is None:
                self.add(prop.line, "D02", node.label(),
                         f"TRIGGER value {v!r} is not a valid DATE-TIME. "
                         "Date-times must be YYYYMMDDTHHMMSS with an "
                         "optional trailing Z — no hyphens, no colons, "
                         "no UTC-offset suffix — with hour 00–23, "
                         "minute 00–59, second 00–60.")
            return
        if vparam in (None, "DURATION"):
            if _parse_duration(prop.value.strip()) is None:
                self.add(prop.line, "E03", node.label(),
                         f"TRIGGER value {prop.value.strip()!r} does not "
                         "match the duration grammar (e.g. -PT15M).")

    # -- V01/V02/V03: required properties ------------------------------------------------
    def _check_required(self, node: Component):
        uid = node.get("UID")
        if uid is None or not uid.value.strip():
            self.add(node.line, "V01", node.label(),
                     f"This {node.name} has no UID"
                     + (" (the UID property is present but empty, and an "
                        "empty string cannot be a globally unique identifier)."
                        if uid is not None else
                        ". Every VEVENT, VTODO, VJOURNAL and VFREEBUSY must "
                        "carry a globally unique UID."))
        if not node.has("DTSTAMP"):
            self.add(node.line, "V02", node.label(),
                     f"This {node.name} has no DTSTAMP. Every VEVENT, VTODO, "
                     "VJOURNAL and VFREEBUSY must include one — a missing "
                     "DTSTAMP is the documented cause of Google Calendar's "
                     "'Unable to launch event' failure.")
        if node.name == "VEVENT" and not node.has("DTSTART"):
            cal = node.parent
            while cal is not None and cal.name != "VCALENDAR":
                cal = cal.parent
            if cal is None or not cal.has("METHOD"):
                self.add(node.line, "V03", node.label(),
                         "This VEVENT has no DTSTART, and its VCALENDAR "
                         "specifies no METHOD. DTSTART is required in that "
                         "case; Google silently rejects events without one.")

    def _check_vevent(self, node: Component):
        if node.has("DTEND") and node.has("DURATION"):
            self.add(node.get("DURATION").line, "E01", node.label(),
                     "This VEVENT carries both DTEND and DURATION. They "
                     "must not occur in the same component — pick one.")

    def _check_vtodo(self, node: Component):
        if node.has("DUE") and node.has("DURATION"):
            self.add(node.get("DURATION").line, "O07", node.label(),
                     "This VTODO carries both DUE and DURATION. They must "
                     "not occur in the same component — pick one.")
        if node.has("DURATION") and not node.has("DTSTART"):
            self.add(node.get("DURATION").line, "V06", node.label(),
                     "This VTODO carries a DURATION but no DTSTART. If a "
                     "duration appears in a to-do, a DTSTART must also "
                     "appear.")

    # -- VFREEBUSY: V07 / O09 ------------------------------------------------------------
    def _check_vfreebusy(self, node: Component):
        for pname in ("DTSTART", "DTEND"):
            prop = node.get(pname)
            if prop is not None:
                v = prop.value.strip()
                if not (_shape_kind(v) == "DATETIME" and v[-1:] in "Zz"):
                    self.add(prop.line, "V07", node.label(),
                             f"VFREEBUSY {pname} value {v!r} is not in UTC "
                             "form. Times in a VFREEBUSY must be specified "
                             "in UTC (trailing Z).")
        for prop in node.getall("FREEBUSY"):
            for period in prop.value.split(","):
                self._check_freebusy_period(node, prop, period.strip())

    def _check_freebusy_period(self, node, prop, period):
        if "/" not in period:
            return  # D02 already fired in the temporal pass
        start, _sep, end = period.partition("/")
        start, end = start.strip(), end.strip()
        sp = _parse_datetime(start)
        if sp is not None and not start[-1:] in "Zz":
            self.add(prop.line, "V07", node.label(),
                     f"FREEBUSY period start {start!r} is not in UTC form. "
                     "FREEBUSY values must be UTC times (trailing Z).")
        if end and end[0].isdigit():
            ep = _parse_datetime(end)
            if ep is not None and not end[-1:] in "Zz":
                self.add(prop.line, "V07", node.label(),
                         f"FREEBUSY period end {end!r} is not in UTC form. "
                         "FREEBUSY values must be UTC times (trailing Z).")
            if sp is not None and ep is not None and not sp[0] < ep[0]:
                self.add(prop.line, "O09", node.label(),
                         f"FREEBUSY period {period!r} does not start before "
                         "it ends. The start of a period must be before "
                         "its end.")
        elif end:
            # start/duration form: judge the duration with E03/E04 grammar.
            if _parse_duration(end) is None:
                self.add(prop.line, "E03", node.label(),
                         f"FREEBUSY period duration {end!r} does not match "
                         "the duration grammar (e.g. PT1H).")
            elif _is_zero_or_negative_duration(end):
                self.add(prop.line, "E04", node.label(),
                         f"FREEBUSY period duration {end!r} is not positive, "
                         "so the period does not start before it ends.")

    # -- VTIMEZONE: T04/T05/T06; observances: T07/T08 ---------------------------------------
    def _canonical(self, node: Component):
        """A hashable canonical form of a component subtree, for
        T04's identical-vs-conflicting comparison.

        Built iteratively, bottom-up: a hostile file can nest
        components thousands of levels deep, and a recursive walk
        would blow the interpreter stack (RecursionError — the F3
        crash). The CLI contract is 'never a traceback', so no walk
        a file can drive may recurse; this was the only one, and
        the rest of the engine (tree building, per-component
        checks, the V04/T03/X01 passes) already iterates over a
        flat node list or an explicit stack.
        """
        done = {}
        stack = [(node, False)]
        while stack:
            current, expanded = stack.pop()
            if not expanded:
                stack.append((current, True))
                for child in current.children:
                    stack.append((child, False))
                continue
            props = tuple(sorted(
                (p.name,
                 tuple((k, tuple(v)) for k, v in sorted(p.params.items())),
                 p.value.strip())
                for p in current.props))
            children = tuple(sorted(done[id(c)] for c in current.children))
            done[id(current)] = (current.name, props, children)
        return done[id(node)]

    def _check_vtimezone(self, node: Component):
        if not node.has("TZID"):
            self.add(node.line, "T05", node.label(),
                     "This VTIMEZONE has no TZID property. A VTIMEZONE must "
                     "include one — it is the name other properties "
                     "reference.")
        if not any(c.name in ("STANDARD", "DAYLIGHT") for c in node.children):
            self.add(node.line, "T06", node.label(),
                     "This VTIMEZONE has no STANDARD or DAYLIGHT "
                     "sub-component. It must include at least one.")

    def _check_t04(self, obj: Component):
        groups = {}
        for child in obj.children:
            if child.name != "VTIMEZONE":
                continue
            tz = child.get("TZID")
            if tz is None:
                continue
            groups.setdefault(tz.value.strip(), []).append(child)
        for tzid, zones in groups.items():
            if len(zones) > 1:
                bodies = {self._canonical(z) for z in zones}
                if len(bodies) > 1:
                    self.add(zones[1].line, "T04", zones[1].label(),
                             f"TZID {tzid!r} is defined by more than one "
                             "VTIMEZONE in this calendar, and the definitions "
                             "differ. Conflicting definitions for one id are "
                             "an error; identical duplicates would not be.")

    def _check_observance(self, node: Component):
        for pname in ("DTSTART", "TZOFFSETFROM", "TZOFFSETTO"):
            if not node.has(pname):
                self.add(node.line, "T07", node.label(),
                         f"This {node.name} observance has no {pname}. Every "
                         "STANDARD/DAYLIGHT sub-component must include "
                         "DTSTART, TZOFFSETFROM and TZOFFSETTO.")
        dtstart = node.get("DTSTART")
        if dtstart is not None:
            v = dtstart.value.strip()
            if _tzid_param(dtstart) is not None or v[-1:] in "Zz":
                self.add(dtstart.line, "T08", node.label(),
                         f"This {node.name} observance's DTSTART is not a "
                         "plain local time — it must be a local date-time "
                         "with no trailing Z and no TZID parameter.")

    # -- D04 / D05 / E02: DTSTART-relative cross-checks ---------------------------------------
    def _dtstart_info(self, node: Component):
        prop = node.get("DTSTART")
        if prop is None:
            return None
        v = prop.value.strip()
        kind = _effective_kind(prop)
        tzid = _tzid_param(prop)
        if kind == "DATETIME":
            form = "UTC" if v[-1:] in "Zz" else "LOCAL"
            parsed = _parse_datetime(v)
            tup = parsed[0] if parsed else None
        elif kind == "DATE":
            form = "DATE"
            tup = None
            if _DATE_SHAPE.match(v) and _valid_date(v):
                tup = (int(v[:4]), int(v[4:6]), int(v[6:8]), 0, 0, 0)
        else:
            form, tup = None, None
        return {"prop": prop, "kind": kind, "form": form, "tzid": tzid,
                "tuple": tup, "value": v}

    def _check_dtstart_relatives(self, node: Component):
        info = self._dtstart_info(node)
        if info is None:
            return
        targets = []
        if node.name in ("VEVENT", "VFREEBUSY"):
            p = node.get("DTEND")
            if p is not None:
                targets.append(("DTEND", p, True))
        if node.name == "VTODO":
            p = node.get("DUE")
            if p is not None:
                targets.append(("DUE", p, True))
        p = node.get("RECURRENCE-ID")
        if p is not None:
            targets.append(("RECURRENCE-ID", p, False))
        for pname, prop, is_end in targets:
            v = prop.value.strip()
            kind = _effective_kind(prop)
            # D04: value kind must match DTSTART's.
            if kind is not None and info["kind"] is not None and kind != info["kind"]:
                self.add(prop.line, "D04", node.label(),
                         f"{pname} is a {kind} value but DTSTART is a "
                         f"{info['kind']} value. They must have the same "
                         "value type.")
                continue
            if kind != "DATETIME" or info["kind"] != "DATETIME":
                # E02 for the both-DATE case.
                if is_end and kind == "DATE" and info["kind"] == "DATE":
                    end_tup = None
                    if _DATE_SHAPE.match(v) and _valid_date(v):
                        end_tup = (int(v[:4]), int(v[4:6]), int(v[6:8]), 0, 0, 0)
                    if end_tup is not None and info["tuple"] is not None:
                        if not end_tup > info["tuple"]:
                            self.add(prop.line, "E02", node.label(),
                                     f"{pname} ({v}) is not later than "
                                     f"DTSTART ({info['value']}). For an "
                                     "all-day event, equal dates are a "
                                     "zero-length event that some importers "
                                     "drop.")
                continue
            # Both DATE-TIME. D05: local/UTC form must agree.
            form = "UTC" if v[-1:] in "Zz" else "LOCAL"
            if form != info["form"]:
                self.add(prop.line, "D05", node.label(),
                         f"{pname} is in {form} form but DTSTART is in "
                         f"{info['form']} form. {pname} must be specified "
                         "as a local time if and only if DTSTART is.")
                continue
            # E02: only for comparable pairs (both UTC, both floating,
            # or both carrying the same TZID).
            if not is_end:
                continue
            parsed = _parse_datetime(v)
            if parsed is None or info["tuple"] is None:
                continue
            tzid = _tzid_param(prop)
            comparable = (
                (form == "UTC" and info["form"] == "UTC")
                or (tzid is None and info["tzid"] is None
                    and form == "LOCAL" and info["form"] == "LOCAL")
                or (tzid is not None and tzid == info["tzid"])
            )
            if comparable and not parsed[0] > info["tuple"]:
                self.add(prop.line, "E02", node.label(),
                         f"{pname} ({v}) is not later than DTSTART "
                         f"({info['value']}). The end of an event must be "
                         "later than its start.")

    # -- V04: duplicate UID + RECURRENCE-ID identity --------------------------------------------
    def _check_v04(self):
        seen = {}
        for obj in self.objects:
            for node in obj.children:
                if node.name not in _EVENT_LIKE:
                    continue
                uid = node.get("UID")
                if uid is None:
                    continue
                rid = node.get("RECURRENCE-ID")
                key = (uid.value.strip(),
                       rid.value.strip() if rid is not None else None)
                if key in seen:
                    self.add(uid.line, "V04", node.label(),
                             f"UID {key[0]!r} is used by more than one "
                             "component with the same RECURRENCE-ID"
                             + (f" ({key[1]})." if key[1] else " (none).")
                             + " A UID must be globally unique; importers "
                             "treat a repeat as an update to the first "
                             "event, not as a new one. Components sharing "
                             "a UID with different RECURRENCE-IDs are legal "
                             "overrides and are not flagged.")
                else:
                    seen[key] = node

    # -- VALARM: O06 / O08 / O10 ------------------------------------------------------------------------
    def _check_valarm(self, node: Component):
        action = node.get("ACTION")
        trigger = node.get("TRIGGER")
        if action is None:
            self.add(node.line, "O06", node.label(),
                     "This VALARM has no ACTION property. A VALARM must "
                     "include ACTION and TRIGGER.")
        if trigger is None:
            self.add(node.line, "O06", node.label(),
                     "This VALARM has no TRIGGER property. A VALARM must "
                     "include ACTION and TRIGGER.")
        if action is not None:
            act = action.value.strip().upper()
            if act == "DISPLAY" and not node.has("DESCRIPTION"):
                self.add(node.line, "O06", node.label(),
                         "This DISPLAY alarm has no DESCRIPTION. A DISPLAY "
                         "alarm must include one — it is the text shown.")
            elif act == "EMAIL":
                missing = [p for p in ("DESCRIPTION", "SUMMARY")
                           if not node.has(p)]
                if not node.has("ATTENDEE"):
                    missing.append("ATTENDEE")
                if missing:
                    self.add(node.line, "O06", node.label(),
                             "This EMAIL alarm is missing "
                             + ", ".join(missing)
                             + ". An EMAIL alarm must include a DESCRIPTION, "
                             "a SUMMARY and at least one ATTENDEE.")
            elif act == "AUDIO" and len(node.getall("ATTACH")) > 1:
                self.add(node.line, "O06", node.label(),
                         "This AUDIO alarm carries more than one ATTACH. "
                         "It may carry at most one.")
        if node.has("DURATION") != node.has("REPEAT"):
            self.add(node.line, "O06", node.label(),
                     "This VALARM has exactly one of DURATION and REPEAT. "
                     "If one occurs, the other must also occur.")
        # O10: REPEAT's value type is INTEGER (§3.8.6.2). On the O04
        # precedent, no range is stated in the spec, so only a
        # non-integer is flagged — a negative integer is not.
        repeat = node.get("REPEAT")
        if repeat is not None and not _INT.match(repeat.value.strip()):
            self.add(repeat.line, "O10", node.label(),
                     f"REPEAT value {repeat.value.strip()!r} is not an "
                     "integer. REPEAT says how many times the alarm "
                     "repeats, and its value type is INTEGER.")
        # O08: absolute TRIGGER presence rules.
        if trigger is not None and _value_param(trigger) == "DATE-TIME":
            parent = node.parent
            if parent is not None and parent.name in ("VEVENT", "VTODO"):
                related_vals = trigger.params.get("RELATED")
                related = related_vals[0].upper() if related_vals else "START"
                if related == "END":
                    if parent.name == "VEVENT":
                        ok = parent.has("DTEND") or (
                            parent.has("DTSTART") and parent.has("DURATION"))
                        need = "a DTEND, or a DTSTART and a DURATION"
                    else:
                        ok = parent.has("DUE") or (
                            parent.has("DTSTART") and parent.has("DURATION"))
                        need = "a DUE, or a DTSTART and a DURATION"
                    if not ok:
                        self.add(trigger.line, "O08", node.label(),
                                 "This alarm has an absolute TRIGGER set "
                                 "relative to the END, but its "
                                 f"{parent.name} has neither {need} — there "
                                 "is no end for the alarm to trigger on.")
                else:
                    if not parent.has("DTSTART"):
                        self.add(trigger.line, "O08", node.label(),
                                 "This alarm has an absolute TRIGGER set "
                                 "relative to the START, but its "
                                 f"{parent.name} has no DTSTART — there is "
                                 "no start for the alarm to trigger on.")


    # -- R01–R12: RRULE ------------------------------------------------------------------------------
    _RRULE_PARTS = {
        "FREQ", "UNTIL", "COUNT", "INTERVAL", "BYSECOND", "BYMINUTE",
        "BYHOUR", "BYDAY", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO",
        "BYMONTH", "BYSETPOS", "WKST",
    }
    _FREQS = {"SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY",
              "MONTHLY", "YEARLY"}
    _WEEKDAYS = {"SU", "MO", "TU", "WE", "TH", "FR", "SA"}
    _BYXXX = {"BYSECOND", "BYMINUTE", "BYHOUR", "BYDAY", "BYMONTHDAY",
              "BYYEARDAY", "BYWEEKNO", "BYMONTH", "BYSETPOS"}

    def _int_list(self, raw):
        vals = []
        for tok in raw.split(","):
            tok = tok.strip()
            if not re.fullmatch(r"[+-]?\d+", tok):
                return None
            vals.append(int(tok))
        return vals

    def _rrule_range(self, node, prop, part, raw, lo_hi_pairs):
        """Range-check a comma-separated integer rule part (R08)."""
        vals = self._int_list(raw)
        if vals is None:
            self.add(prop.line, "R08", node.label(),
                     f"RRULE {part} value {raw!r} is not a list of integers.")
            return
        for val in vals:
            if not any(lo <= val <= hi for lo, hi in lo_hi_pairs):
                self.add(prop.line, "R08", node.label(),
                         f"RRULE {part} value {val} is out of range. "
                         f"Allowed: "
                         + " or ".join(f"{lo} to {hi}" for lo, hi in lo_hi_pairs)
                         + ".")
                return

    def _check_rrule(self, node, prop):
        parts = []       # (name, raw value or None)
        for chunk in prop.value.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" in chunk:
                n, v = chunk.split("=", 1)
                parts.append((n.strip().upper(), v.strip()))
            else:
                parts.append((chunk.upper(), None))
        names = [n for n, _v in parts]
        first = {}
        for n, v in parts:
            first.setdefault(n, v)

        # R05: unknown parts (or parts with no '=').
        for n, v in parts:
            if n not in self._RRULE_PARTS or v is None:
                self.add(prop.line, "R05", node.label(),
                         f"RRULE contains a rule part {n!r} that is not in "
                         "the spec's closed set (FREQ, UNTIL, COUNT, "
                         "INTERVAL, BYSECOND, BYMINUTE, BYHOUR, BYDAY, "
                         "BYMONTHDAY, BYYEARDAY, BYWEEKNO, BYMONTH, "
                         "BYSETPOS, WKST). Parsers may ignore or choke on it.")
        # R04: duplicated parts.
        seen_once = set()
        for n in names:
            if n in seen_once:
                self.add(prop.line, "R04", node.label(),
                         f"RRULE rule part {n} occurs more than once. "
                         "Individual rule parts must only be specified once.")
                break
            seen_once.add(n)
        # R01 / R02: FREQ.
        freq = first.get("FREQ")
        if freq is None and "FREQ" not in names:
            self.add(prop.line, "R01", node.label(),
                     "This RRULE has no FREQ rule part. FREQ is required in "
                     "every recurrence rule.")
        freq_u = freq.upper() if freq else None
        if freq_u is not None and freq_u not in self._FREQS:
            self.add(prop.line, "R02", node.label(),
                     f"RRULE FREQ value {freq!r} is not one of SECONDLY, "
                     "MINUTELY, HOURLY, DAILY, WEEKLY, MONTHLY, YEARLY.")
        # R03: COUNT + UNTIL.
        if "COUNT" in names and "UNTIL" in names:
            self.add(prop.line, "R03", node.label(),
                     "This RRULE carries both COUNT and UNTIL. They must "
                     "not occur in the same recurrence rule — pick one.")
        # R08: ranges and tokens.
        rng = self._rrule_range
        if first.get("BYSECOND") is not None:
            rng(node, prop, "BYSECOND", first["BYSECOND"], [(0, 60)])
        if first.get("BYMINUTE") is not None:
            rng(node, prop, "BYMINUTE", first["BYMINUTE"], [(0, 59)])
        if first.get("BYHOUR") is not None:
            rng(node, prop, "BYHOUR", first["BYHOUR"], [(0, 23)])
        if first.get("BYMONTH") is not None:
            rng(node, prop, "BYMONTH", first["BYMONTH"], [(1, 12)])
        if first.get("BYMONTHDAY") is not None:
            rng(node, prop, "BYMONTHDAY", first["BYMONTHDAY"],
                [(1, 31), (-31, -1)])
        if first.get("BYYEARDAY") is not None:
            rng(node, prop, "BYYEARDAY", first["BYYEARDAY"],
                [(1, 366), (-366, -1)])
        if first.get("BYWEEKNO") is not None:
            rng(node, prop, "BYWEEKNO", first["BYWEEKNO"],
                [(1, 53), (-53, -1)])
        if first.get("BYSETPOS") is not None:
            rng(node, prop, "BYSETPOS", first["BYSETPOS"],
                [(1, 366), (-366, -1)])
        byday_has_ordinal = False
        if first.get("BYDAY") is not None:
            for tok in first["BYDAY"].split(","):
                tok = tok.strip()
                m = re.fullmatch(r"([+-]?\d+)?([A-Za-z]{2})", tok)
                if not m or m.group(2).upper() not in self._WEEKDAYS:
                    self.add(prop.line, "R08", node.label(),
                             f"RRULE BYDAY token {tok!r} is not a weekday "
                             "(SU, MO, TU, WE, TH, FR, SA) with an optional "
                             "ordinal.")
                    break
                if m.group(1) is not None:
                    byday_has_ordinal = True
                    ordinal = int(m.group(1))
                    if not (1 <= ordinal <= 53 or -53 <= ordinal <= -1):
                        self.add(prop.line, "R08", node.label(),
                                 f"RRULE BYDAY ordinal {ordinal} is out of "
                                 "range (1 to 53 or -53 to -1).")
                        break
        if first.get("WKST") is not None:
            if first["WKST"].upper() not in self._WEEKDAYS:
                self.add(prop.line, "R08", node.label(),
                         f"RRULE WKST value {first['WKST']!r} is not a "
                         "weekday (MO, TU, WE, TH, FR, SA, SU).")
        if first.get("COUNT") is not None:
            if not re.fullmatch(r"\d+", first["COUNT"]):
                self.add(prop.line, "R08", node.label(),
                         f"RRULE COUNT value {first['COUNT']!r} is not a "
                         "non-negative integer.")
        if first.get("INTERVAL") is not None:
            iv = first["INTERVAL"]
            if not re.fullmatch(r"\d+", iv) or int(iv) == 0:
                self.add(prop.line, "R08", node.label(),
                         f"RRULE INTERVAL value {iv!r} is not a positive "
                         "integer. INTERVAL must be a positive integer.")
        # DTSTART-relative checks (R06 / R07 / R12) and R09 combos.
        dtstart = node.get("DTSTART")
        ds_kind = ds_form = None
        if dtstart is not None:
            dv = dtstart.value.strip()
            ds_kind = _effective_kind(dtstart)
            if ds_kind == "DATETIME":
                ds_form = "UTC" if dv[-1:] in "Zz" else "LOCAL"
        in_observance = node.name in ("STANDARD", "DAYLIGHT")
        until = first.get("UNTIL")
        if until is not None:
            u_kind = _shape_kind(until)
            # A malformed UNTIL value is a D01/D02 defect.
            if u_kind == "DATE":
                if not _valid_date(until):
                    self.add(prop.line, "D01", node.label(),
                             f"RRULE UNTIL value {until!r} is not a valid "
                             "DATE (YYYYMMDD, and the day must exist).")
            elif u_kind == "DATETIME" or "T" in until or "t" in until:
                if _parse_datetime(until) is None:
                    self.add(prop.line, "D02", node.label(),
                             f"RRULE UNTIL value {until!r} is not a valid "
                             "DATE-TIME (YYYYMMDDTHHMMSS, optional Z).")
            else:
                self.add(prop.line, "D02", node.label(),
                         f"RRULE UNTIL value {until!r} is neither a DATE "
                         "nor a DATE-TIME.")
            if ds_kind is not None and u_kind is not None:
                if in_observance:
                    # Inside STANDARD/DAYLIGHT, every UNTIL form
                    # defect is R12's: §3.3.10 requires UNTIL there
                    # to be a UTC date-time, full stop — a DATE
                    # included. R06 is suppressed here so the defect
                    # is attributed to R12, as designed; R07 never
                    # applies in observances (its own scoping).
                    if not (u_kind == "DATETIME" and until[-1:] in "Zz"):
                        self.add(prop.line, "R12", node.label(),
                                 "Inside a STANDARD/DAYLIGHT "
                                 "observance, the RRULE UNTIL must "
                                 "always be a date-time in UTC form "
                                 f"(trailing Z); {until!r} is not.")
                elif u_kind != ds_kind:
                    self.add(prop.line, "R06", node.label(),
                             f"RRULE UNTIL is a {u_kind} value but DTSTART "
                             f"is a {ds_kind} value. UNTIL must have the "
                             "same value type as DTSTART.")
                elif u_kind == "DATETIME":
                    u_utc = until[-1:] in "Zz"
                    # R07: UTC-ness must agree with DTSTART's form.
                    if ds_form == "UTC" and not u_utc:
                        self.add(prop.line, "R07", node.label(),
                                 "DTSTART is in UTC form (or carries a "
                                 "TZID) but RRULE UNTIL is not a UTC "
                                 f"date-time: {until!r}. Google drops "
                                 "or truncates series with this defect.")
                    elif ds_form == "LOCAL" and u_utc:
                        # DTSTART with a TZID counts as 'UTC side' of
                        # the §3.3.10 sentence; floating does not.
                        if _tzid_param(dtstart) is not None:
                            pass  # TZID start + UTC UNTIL is correct
                        else:
                            self.add(prop.line, "R07", node.label(),
                                     "DTSTART is a floating local time "
                                     "but RRULE UNTIL is a UTC "
                                     f"date-time: {until!r}. When "
                                     "DTSTART is local time, UNTIL must "
                                     "also be local time.")
                    elif ds_form == "LOCAL" and not u_utc:
                        pass  # both local: fine
                    if ds_form == "UTC" and u_utc:
                        pass
                    # DTSTART TZID + UNTIL not UTC is the remaining R07 case.
                    if (ds_form == "LOCAL"
                            and _tzid_param(dtstart) is not None and not u_utc):
                        self.add(prop.line, "R07", node.label(),
                                 "DTSTART carries a TZID but RRULE UNTIL is "
                                 f"not a UTC date-time: {until!r}. When "
                                 "DTSTART has a time zone reference, UNTIL "
                                 "must be specified in UTC time.")
        # R09: forbidden combinations.
        partset = set(names)
        if freq_u in self._FREQS or freq_u is None:
            if "BYWEEKNO" in partset and freq_u != "YEARLY" and freq_u is not None:
                self.add(prop.line, "R09", node.label(),
                         "RRULE uses BYWEEKNO with FREQ other than YEARLY. "
                         "BYWEEKNO must not be used with any other FREQ.")
            if "BYMONTHDAY" in partset and freq_u == "WEEKLY":
                self.add(prop.line, "R09", node.label(),
                         "RRULE uses BYMONTHDAY with FREQ=WEEKLY. "
                         "BYMONTHDAY must not be specified with WEEKLY.")
            if "BYYEARDAY" in partset and freq_u in ("DAILY", "WEEKLY", "MONTHLY"):
                self.add(prop.line, "R09", node.label(),
                         f"RRULE uses BYYEARDAY with FREQ={freq_u}. "
                         "BYYEARDAY must not be specified with DAILY, "
                         "WEEKLY or MONTHLY.")
            if byday_has_ordinal and freq_u is not None:
                if freq_u not in ("MONTHLY", "YEARLY") or (
                        freq_u == "YEARLY" and "BYWEEKNO" in partset):
                    self.add(prop.line, "R09", node.label(),
                             "RRULE uses BYDAY with a numeric ordinal where "
                             "that is not allowed: a numeric BYDAY requires "
                             "FREQ=MONTHLY or YEARLY, and must not be used "
                             "with YEARLY when BYWEEKNO is present.")
            if ds_kind == "DATE" and partset & {"BYSECOND", "BYMINUTE", "BYHOUR"}:
                self.add(prop.line, "R09", node.label(),
                         "RRULE uses BYSECOND, BYMINUTE or BYHOUR while "
                         "DTSTART is a DATE. Those parts must not be used "
                         "with a DATE start; parsers are required to ignore "
                         "them, so the recurrence will not do what the "
                         "file says.")
            if "BYSETPOS" in partset and not (partset & (self._BYXXX - {"BYSETPOS"})):
                self.add(prop.line, "R09", node.label(),
                         "RRULE uses BYSETPOS with no other BYxxx rule "
                         "part. BYSETPOS must only be used in conjunction "
                         "with another BYxxx part.")

    # -- X01: orphan RECURRENCE-ID overrides ------------------------------------------------------------
    def _check_x01(self):
        for obj in self.objects:
            masters = set()
            for node in obj.children:
                if node.name in ("VEVENT", "VTODO", "VJOURNAL"):
                    uid = node.get("UID")
                    if uid is not None and not node.has("RECURRENCE-ID"):
                        masters.add(uid.value.strip())
            for node in obj.children:
                if node.name not in ("VEVENT", "VTODO", "VJOURNAL"):
                    continue
                rid = node.get("RECURRENCE-ID")
                uid = node.get("UID")
                if rid is not None and uid is not None:
                    if uid.value.strip() not in masters:
                        self.add(rid.line, "X01", node.label(),
                                 "This component carries a RECURRENCE-ID "
                                 "but no master component with the same UID "
                                 "(and no RECURRENCE-ID) exists in this "
                                 "iCalendar object. In an import file, "
                                 "Google either discards such orphan "
                                 "overrides or turns them into standalone "
                                 "events on the wrong date.")


def lint_bytes(data: bytes, filename: str):
    """Lint one .ics file's raw bytes. Returns a list of Finding."""
    return _Linter(filename).run(data)


def lint_file(path: str, display_name=None):
    """Read and lint one file. Raises OSError if it cannot be read."""
    with open(path, "rb") as fh:
        data = fh.read()
    return lint_bytes(data, display_name if display_name is not None else path)
