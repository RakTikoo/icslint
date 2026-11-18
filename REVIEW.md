# Build verification — icslint v0.1.0

Builder's verification summary, 2026-11-18. This records what was
actually run. The independent adversarial review of the *design*
predates the build (DESIGN_REVIEW.md, internal). A fresh-eyes
review of the built code followed (CODE_REVIEW.md, internal); it
found real defects, and the fixes are recorded in the
code-review round section below — that section was written by
the fixer, not the original builder.

## What was built

- `icslint/` package (`core.py` lint engine with all 67 rules from
  DESIGN.md as data + checks, `cli.py` for the `check` command,
  `--strict`, `--format text|json`, exit codes 0/1/2).
- `tests/` — 67 per-rule violating fixtures, 19 valid-corpus files,
  6 code-review regression fixtures, `test_icslint.py`.
- `examples/clean.ics` and `examples/broken.ics` (five seeded
  defects: V02, E02, R03, W01, V04 — verified to produce exactly
  those five findings).
- `README.md` with the demo output captured from an actual run and
  the Honest limits section the design requires.

## What was run

- **Full test battery** (`python3 run_tests.py`): **29 tests, all
  passing** as built; **36 tests, all passing** after the
  code-review round below. The per-rule test iterates all 67
  fixtures as subtests and asserts each fires *exactly* its own
  rule at the designed severity (no cross-talk); the corpus test
  iterates all 19 valid files and asserts zero findings on each.
- **Fresh-venv install**: new venv + `pip install` of the local
  tree succeeded (zero dependencies); the installed `icslint`
  console script reproduced the demo (broken.ics → exit 1,
  clean.ics → exit 0, no-args → exit 2). Re-run after the
  code-review fixes, including the new O10 fixture → exit 1.
- **README demo**: produced by running the tool on
  `examples/broken.ics` and pasting the output verbatim.
- **Adversarial probes by the builder** (inline, not in the suite):
  TZID DTSTART + UTC UNTIL in a normal event (clean — the §3.3.10
  form R07 must not flag), tab-indented fold (clean), O08 START
  variant in a DTSTART-less VTODO (fires once), BYSETPOS alone
  (R09) vs BYSETPOS with BYDAY (clean), and a 1 KB binary-garbage
  file (single S08 finding, no crash).

## Bugs found by the fixture run and fixed before this summary

1. **S04 files were misreported as S08.** A fold that splits a
   UTF-8 character makes the *raw* byte stream undecodable as a
   flat sequence; the original code decoded the raw stream first
   and cried "not UTF-8". Fixed: unfolding now happens at the byte
   level and the UTF-8 check runs on the unfolded logical lines
   (a UTF-16 file still fails there and reports S08 alone).
2. **D03 cross-talk into D04.** For a property whose VALUE=
   parameter disagrees with its shape, cross-checks used the
   declared kind, so a D03 defect also drew a spurious D04. Fixed:
   cross-checks use an *effective kind* (shape first; the parameter
   only when the shape is indeterminate) — D03 owns that defect.
3. Two valid-corpus fixtures contained unescaped commas in SUMMARY
   — the linter was right (W01) and the fixtures were wrong; the
   fixture texts were corrected.

## Code-review round (2026-11-18)

The independent review of the built code (CODE_REVIEW.md) ran ~75
hostile probes and found two false positives, one crash, two
false negatives and one rule-attribution drift — plus two
provable design gaps in its observations. All were fixed; the
design amendments are recorded in DESIGN.md's code-review gap
log. Status of every item: **fixed, pending re-measure** (the
re-measure is the gauntlet step that follows this round).

- **F1 (false positive, serious)** — D03 fired on every property
  carrying an explicit `VALUE=DATE-TIME`: the internal shape token
  `DATETIME` was compared raw against the parameter token
  `DATE-TIME`. Kind tokens are now canonicalised at every
  comparison; a valid fixture with explicit VALUE=DATE-TIME on
  DTSTART/DTEND/DTSTAMP/EXDATE pins it.
- **F2 (false positive)** — grouped property names
  (`home.DTSTART:`) were not recognised, so a conforming event
  drew V03. The parser now strips §3.1 group prefixes; DESIGN.md
  gained the group-prefix paragraph it was missing.
- **F3 (crash)** — a duplicated TZID plus ~2000 nested components
  drove the recursive `_canonical` into a RecursionError
  traceback. `_canonical` is now iterative (it was the only
  file-driven recursion in the engine; the audit is recorded in
  its docstring). Regression tests pin the input at lint and CLI
  level: findings and exit 1, no traceback.
- **F4 (false negative)** — BOM-less UTF-16 and a lone NUL byte
  escaped S08, contrary to DESIGN.md's explicit "fail on the
  first NUL" claim: the mechanism was never implemented. Any NUL
  byte now reports S08 alone. Two regression fixtures pin both
  forms at exactly S08.
- **F5 (false negative)** — a malformed DURATION inside a VALARM
  was silent. E03's grammar now applies to the DURATION property
  in VALARM too (DESIGN.md's E03 row amended to state the scope;
  E04/E05 remain VEVENT/VTODO-only).
- **F6 (drift)** — an observance UNTIL given as a DATE was
  reported as R06, not R12. R06 is now suppressed inside
  STANDARD/DAYLIGHT so R12 owns every UNTIL form defect there,
  as designed; a regression fixture asserts R12 fires and R06
  does not.
- **A1 (design amendment)** — TRIGGER joins the D-section's
  property list in its VALUE=DATE-TIME form: an impossible
  absolute trigger date is now D02 (it previously passed clean).
- **A2 (design amendment)** — new rule **O10**: a VALARM REPEAT
  that is not an integer (ERROR, §3.8.6.2). No range is imposed,
  on the O04 precedent. Rule count 66 → 67 (58 ERROR, 9 WARNING).

What the fixer re-ran after the fixes: the full battery (36
tests, green), the review's probe files for F1–F6 and both
amendments (each now behaves exactly as designed), the review's
full ~75-probe sweep (no other probe changed behaviour; no
traceback anywhere), the examples demo (output unchanged,
byte-for-byte as in the README), and the fresh-venv install.

## Deviations from DESIGN.md

None in rule coverage or severity. Two interpretation notes, both
recorded in code comments:

- V04 grouping excludes components with no UID property at all
  (a missing UID is V01's defect); components with an *empty* UID
  do participate, per the design's V01 rationale.
- FREEBUSY period durations are judged with the E03/E04 grammar,
  as O09's text delegates; a structurally malformed FREEBUSY period
  (no `/`) is reported as D02.
