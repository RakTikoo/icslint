"""Tests for icslint.

The oracle is DESIGN.md's rule list: one violating fixture per rule
(each must fire exactly that rule, with the designed severity), a
valid corpus of real-world-shaped files (each must produce ZERO
findings — false positives are the mortal sin of a linter), the
anti-rules pinned individually, and the CLI contract (exit codes,
--strict, --format json, folder scanning, no tracebacks).
"""

import glob
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from icslint.cli import main
from icslint.core import RULES, lint_bytes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIOLATIONS = os.path.join(ROOT, "tests", "fixtures", "violations")
VALID = os.path.join(ROOT, "tests", "fixtures", "valid")
REGRESSIONS = os.path.join(ROOT, "tests", "fixtures", "regressions")
EXAMPLES = os.path.join(ROOT, "examples")


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _lint_fixture(folder, name):
    path = os.path.join(folder, name)
    return lint_bytes(_read(path), path)


def _crlf(*lines):
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


_BASE = [
    "BEGIN:VCALENDAR", "PRODID:-//icslint tests//EN", "VERSION:2.0",
    "BEGIN:VEVENT", "UID:u1@test", "DTSTAMP:20260101T000000Z",
    "DTSTART:20260601T090000Z", "DTEND:20260601T100000Z",
    "SUMMARY:Test event", "END:VEVENT", "END:VCALENDAR",
]


class TestRuleFixtures(unittest.TestCase):
    """One violating fixture per rule: the rule fires, with the
    designed severity, and no other rule fires alongside it."""

    def test_every_rule_has_a_fixture(self):
        files = {os.path.basename(p)[:-4].upper()
                 for p in glob.glob(os.path.join(VIOLATIONS, "*.ics"))}
        self.assertEqual(files, set(RULES))

    def test_each_fixture_fires_exactly_its_rule(self):
        for rule in sorted(RULES):
            with self.subTest(rule=rule):
                findings = _lint_fixture(VIOLATIONS, rule.lower() + ".ics")
                fired = {f.rule for f in findings}
                self.assertEqual(fired, {rule},
                                 f"{rule} fixture fired {sorted(fired)}")
                for f in findings:
                    self.assertEqual(f.severity, RULES[rule][0])
                    self.assertTrue(f.message)
                    self.assertTrue(f.source)
                    self.assertGreaterEqual(f.line, 1)


class TestValidCorpus(unittest.TestCase):
    """Real-world-shaped valid files must produce zero findings."""

    def test_valid_corpus_is_clean(self):
        paths = sorted(glob.glob(os.path.join(VALID, "*.ics")))
        self.assertGreaterEqual(len(paths), 15)
        for path in paths:
            with self.subTest(file=os.path.basename(path)):
                findings = lint_bytes(_read(path), path)
                self.assertEqual(
                    findings, [],
                    f"{os.path.basename(path)}: "
                    + "; ".join(f"{f.rule}@{f.line}: {f.message}"
                                for f in findings))

    def test_examples_clean_file_is_clean(self):
        findings = _lint_fixture(EXAMPLES, "clean.ics")
        self.assertEqual(findings, [])


class TestAntiRules(unittest.TestCase):
    """Legal constructs that must never be flagged (DESIGN.md)."""

    def assert_clean(self, data):
        self.assertEqual(lint_bytes(data, "inline.ics"), [])

    def test_lowercase_names_and_values(self):
        self.assert_clean(_crlf(
            "begin:vcalendar", "prodid:-//x//en", "version:2.0",
            "begin:vevent", "uid:a@b", "dtstamp:20260101t000000z",
            "dtstart:20260601t090000z", "dtend:20260601t100000z",
            "rrule:freq=daily;count=5", "transp:opaque",
            "end:vevent", "end:vcalendar"))

    def test_x_and_unknown_properties_ignored(self):
        lines = list(_BASE)
        lines.insert(8, "X-CUSTOM-PROP:anything;here")
        lines.insert(9, "FUTUREPROP:whatever")
        self.assert_clean(_crlf(*lines))

    def test_rfc_vtimezone_example_pattern(self):
        # The RFC's own observance pattern: local DTSTART, UTC UNTIL.
        self.assert_clean(_crlf(
            "BEGIN:VCALENDAR", "PRODID:-//x//EN", "VERSION:2.0",
            "BEGIN:VTIMEZONE", "TZID:America/New_York",
            "BEGIN:DAYLIGHT", "DTSTART:19670430T020000",
            "RRULE:FREQ=YEARLY;BYMONTH=4;BYDAY=-1SU;UNTIL=19730429T070000Z",
            "TZOFFSETFROM:-0500", "TZOFFSETTO:-0400", "END:DAYLIGHT",
            "END:VTIMEZONE", "END:VCALENDAR"))

    def test_floating_times_are_legal(self):
        self.assert_clean(_crlf(
            "BEGIN:VCALENDAR", "PRODID:-//x//EN", "VERSION:2.0",
            "BEGIN:VEVENT", "UID:a@b", "DTSTAMP:20260101T000000Z",
            "DTSTART:20260601T090000", "DTEND:20260601T100000",
            "END:VEVENT", "END:VCALENDAR"))

    def test_missing_summary_and_dtend_are_legal(self):
        self.assert_clean(_crlf(
            "BEGIN:VCALENDAR", "PRODID:-//x//EN", "VERSION:2.0",
            "BEGIN:VEVENT", "UID:a@b", "DTSTAMP:20260101T000000Z",
            "DTSTART:20260601T090000Z",
            "END:VEVENT", "END:VCALENDAR"))

    def test_leap_second_and_exactly_75_octets(self):
        line = "SUMMARY:" + "x" * 67  # exactly 75 octets
        self.assertEqual(len(line.encode()), 75)
        self.assert_clean(_crlf(
            "BEGIN:VCALENDAR", "PRODID:-//x//EN", "VERSION:2.0",
            "BEGIN:VEVENT", "UID:a@b", "DTSTAMP:20170101T000000Z",
            "DTSTART:20161231T235960Z", "DTEND:20170101T000000Z",
            line, "END:VEVENT", "END:VCALENDAR"))

    def test_same_uid_different_recurrence_ids_are_legal(self):
        findings = _lint_fixture(VALID, "overrides.ics")
        self.assertEqual(findings, [])

    def test_rrule_neither_count_nor_until_is_legal(self):
        self.assert_clean(_crlf(
            "BEGIN:VCALENDAR", "PRODID:-//x//EN", "VERSION:2.0",
            "BEGIN:VEVENT", "UID:a@b", "DTSTAMP:20260101T000000Z",
            "DTSTART:20260601T090000Z", "RRULE:FREQ=YEARLY",
            "END:VEVENT", "END:VCALENDAR"))

    def test_count_zero_is_not_flagged(self):
        self.assert_clean(_crlf(
            "BEGIN:VCALENDAR", "PRODID:-//x//EN", "VERSION:2.0",
            "BEGIN:VEVENT", "UID:a@b", "DTSTAMP:20260101T000000Z",
            "DTSTART:20260601T090000Z", "RRULE:FREQ=DAILY;COUNT=0",
            "END:VEVENT", "END:VCALENDAR"))

    def test_negative_sequence_is_not_flagged(self):
        lines = list(_BASE)
        lines.insert(8, "SEQUENCE:-1")
        self.assert_clean(_crlf(*lines))

    def test_method_on_vcalendar_is_legal(self):
        findings = _lint_fixture(VALID, "multi_object.ics")
        self.assertEqual(findings, [])

    def test_identical_duplicate_vtimezone_is_legal(self):
        findings = _lint_fixture(VALID, "duplicate_vtimezone_identical.ics")
        self.assertEqual(findings, [])

    def test_explicit_value_datetime_params_are_legal(self):
        # F1 regression: an explicit VALUE=DATE-TIME that matches the
        # value's form is conforming — the parameter spelling
        # (DATE-TIME) and the internal kind token must not be
        # compared raw.
        findings = _lint_fixture(VALID, "value_datetime_params.ics")
        self.assertEqual(findings, [])
        self.assert_clean(_crlf(
            "BEGIN:VCALENDAR", "PRODID:-//x//EN", "VERSION:2.0",
            "BEGIN:VEVENT", "UID:a@b",
            "DTSTAMP;VALUE=DATE-TIME:20260101T000000Z",
            "DTSTART;VALUE=DATE-TIME:20260601T090000Z",
            "DTEND;VALUE=DATE-TIME:20260601T100000Z",
            "END:VEVENT", "END:VCALENDAR"))

    def test_grouped_property_names_are_recognised(self):
        # F2 regression: §3.1 allows a group prefix ("home.DTSTART");
        # a grouped DTSTART *is* a DTSTART.
        findings = _lint_fixture(VALID, "grouped.ics")
        self.assertEqual(findings, [])
        self.assert_clean(_crlf(
            "BEGIN:VCALENDAR", "PRODID:-//x//EN", "VERSION:2.0",
            "BEGIN:VEVENT", "home.UID:a@b",
            "home.DTSTAMP:20260101T000000Z",
            "home.DTSTART:20260601T090000Z",
            "home.DTEND:20260601T100000Z",
            "END:VEVENT", "END:VCALENDAR"))

    def test_negative_repeat_is_not_flagged(self):
        # O10 follows the O04 precedent: §3.8.6.2 states REPEAT's
        # INTEGER type but no range, so only a non-integer fires.
        lines = list(_BASE)
        lines[8:8] = [
            "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15M",
            "DURATION:PT5M", "REPEAT:-1", "DESCRIPTION:Reminder",
            "END:VALARM",
        ]
        self.assert_clean(_crlf(*lines))


class TestEdgeCases(unittest.TestCase):
    def test_empty_file_reports_c01_not_a_crash(self):
        findings = lint_bytes(b"", "empty.ics")
        self.assertEqual({f.rule for f in findings}, {"C01"})

    def test_garbage_file_reports_not_a_crash(self):
        findings = lint_bytes(b"hello world\nthis is not a calendar\n",
                              "junk.ics")
        self.assertTrue(findings)
        self.assertTrue(all(f.severity in ("ERROR", "WARNING")
                            for f in findings))

    def test_unterminated_final_line_is_s01(self):
        data = _crlf(*_BASE)[:-2]  # strip the final CRLF
        rules = {f.rule for f in lint_bytes(data, "x.ics")}
        self.assertIn("S01", rules)

    def test_version_range_form_is_accepted(self):
        lines = list(_BASE)
        lines[2] = "VERSION:1.0;2.0"
        self.assertEqual(lint_bytes(_crlf(*lines), "x.ics"), [])

    def test_fold_inside_utf8_is_warning_not_error(self):
        findings = _lint_fixture(VIOLATIONS, "s04.ics")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "WARNING")

    def test_importer_sourced_rules_are_labelled(self):
        findings = _lint_fixture(VIOLATIONS, "x01.ics")
        self.assertEqual(findings[0].source_type, "Importer behaviour")
        self.assertIn("Importer behaviour", findings[0].source)


class TestCodeReviewRegressions(unittest.TestCase):
    """One fixture per defect the independent code review found
    (CODE_REVIEW.md, F1–F6 plus the TRIGGER/O10 amendments). Each
    must fire exactly the designed rule — no more, no less."""

    EXPECTED = {
        # F4: BOM-less UTF-16 and a lone NUL both report S08 alone.
        "utf16le_no_bom.ics": {"S08"},
        "nul_in_value.ics": {"S08"},
        # F5: the duration grammar applies inside VALARM too.
        "valarm_bad_duration.ics": {"E03"},
        # F6: a DATE UNTIL in an observance is R12, not R06.
        "observance_until_date.ics": {"R12"},
        # Amendment: an impossible absolute TRIGGER date is D02.
        "trigger_bad_datetime.ics": {"D02"},
        # Amendment: REPEAT's INTEGER type is O10.
        "repeat_not_integer.ics": {"O10"},
    }

    def test_regression_fixtures(self):
        for name, expected in sorted(self.EXPECTED.items()):
            with self.subTest(file=name):
                findings = _lint_fixture(REGRESSIONS, name)
                self.assertEqual({f.rule for f in findings}, expected)

    def test_observance_until_date_is_r12_not_r06(self):
        findings = _lint_fixture(REGRESSIONS, "observance_until_date.ics")
        self.assertEqual([f.rule for f in findings], ["R12"])

    @staticmethod
    def _deep_duplicate_tzid(depth):
        lines = ["BEGIN:VCALENDAR", "PRODID:-//x//EN", "VERSION:2.0",
                 "BEGIN:VTIMEZONE", "TZID:Dup/Zone"]
        lines += ["BEGIN:X-DEEP"] * depth
        lines += ["END:X-DEEP"] * depth
        lines += ["END:VTIMEZONE",
                  "BEGIN:VTIMEZONE", "TZID:Dup/Zone",
                  "BEGIN:STANDARD", "DTSTART:19700101T000000",
                  "TZOFFSETFROM:+0000", "TZOFFSETTO:+0000",
                  "END:STANDARD", "END:VTIMEZONE", "END:VCALENDAR"]
        return _crlf(*lines)

    def test_deep_nesting_duplicate_tzid_does_not_crash(self):
        # F3: the T04 canonicalisation must be depth-safe — 2000
        # nested components inside a duplicated-TZID VTIMEZONE
        # used to end in a RecursionError traceback.
        findings = lint_bytes(self._deep_duplicate_tzid(2000), "deep.ics")
        self.assertIn("T04", {f.rule for f in findings})

    def test_deep_nesting_duplicate_tzid_cli_no_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "deep.ics")
            with open(path, "wb") as fh:
                fh.write(self._deep_duplicate_tzid(2000))
            code, _out, err = _run_cli(["check", path])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)


def _run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCli(unittest.TestCase):
    def test_clean_file_exits_0(self):
        code, out, _err = _run_cli(
            ["check", os.path.join(EXAMPLES, "clean.ics")])
        self.assertEqual(code, 0)
        self.assertIn("no findings", out)

    def test_broken_file_exits_1_and_names_rules(self):
        code, out, _err = _run_cli(
            ["check", os.path.join(EXAMPLES, "broken.ics")])
        self.assertEqual(code, 1)
        for rule in ("V02", "E02", "R03", "W01", "V04"):
            self.assertIn(rule, out)
        self.assertIn("4 errors, 1 warning", out)

    def test_warnings_only_exits_0_unless_strict(self):
        path = os.path.join(VIOLATIONS, "w01.ics")
        code, _o, _e = _run_cli(["check", path])
        self.assertEqual(code, 0)
        code, _o, _e = _run_cli(["check", "--strict", path])
        self.assertEqual(code, 1)

    def test_json_format(self):
        code, out, _err = _run_cli(
            ["check", "--format", "json",
             os.path.join(EXAMPLES, "broken.ics")])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["files_checked"], 1)
        self.assertEqual(payload["errors"], 4)
        self.assertEqual(payload["warnings"], 1)
        self.assertEqual({f["rule"] for f in payload["findings"]},
                         {"V02", "E02", "R03", "W01", "V04"})
        for f in payload["findings"]:
            self.assertIn("source", f)
            self.assertIn("source_type", f)
            self.assertIn("component", f)

    def test_missing_path_exits_2_one_line_no_traceback(self):
        code, _out, err = _run_cli(["check", "/nonexistent/nope.ics"])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_folder_scan_is_recursive_and_case_insensitive(self):
        with tempfile.TemporaryDirectory() as td:
            sub = os.path.join(td, "sub")
            os.makedirs(sub)
            with open(os.path.join(td, "a.ics"), "wb") as fh:
                fh.write(_read(os.path.join(EXAMPLES, "clean.ics")))
            with open(os.path.join(sub, "B.ICS"), "wb") as fh:
                fh.write(_read(os.path.join(EXAMPLES, "broken.ics")))
            with open(os.path.join(td, "ignore.txt"), "wb") as fh:
                fh.write(b"junk")
            code, out, _err = _run_cli(["check", td])
            self.assertEqual(code, 1)
            self.assertIn("2 files checked", out)
            self.assertIn("B.ICS", out)

    def test_single_file_argument_checked_even_without_ics_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "calendar.txt")
            with open(path, "wb") as fh:
                fh.write(_read(os.path.join(EXAMPLES, "clean.ics")))
            code, _out, _err = _run_cli(["check", path])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
