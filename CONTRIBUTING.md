# Contributing

Thanks for looking at icslint. Issues and pull requests are welcome.

## Before you start

- For a starter issue, claim it with a comment first, so two people do not build the same thing.
- Keep each change small and focused on one issue.

## Running the tests

```console
python3 run_tests.py
```

The full suite (36 tests, stdlib `unittest`, no dependencies) must pass before a pull request is reviewed. Two bars are absolute: the valid corpus must still produce zero findings (a conforming file is silent — that is the tested guarantee), and every rule needs a source: an RFC 5545 section, or a named, dated importer source labelled "Importer behaviour". The two are never blended. The stated non-goals are not bugs: no recurrence expansion, and no DST/VTIMEZONE transition semantics. If your change alters the CLI or its output, update the README in the same pull request — and SKILL.md too, if install, commands, flags, exit codes or output wording changed.

## Pull requests

- Say what you changed, how you tested it, and which source each new rule cites.
