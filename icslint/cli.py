"""Command-line interface for icslint."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .core import lint_file


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="icslint",
        description="Lint iCalendar (.ics) files against the requirements "
        "RFC 5545 actually states and the import failures Google, Outlook "
        "and Apple Calendar are documented to have.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    check = sub.add_parser(
        "check", help="check one .ics file, or every .ics file in a folder")
    check.add_argument("path", help="an .ics file, or a folder scanned "
                       "recursively for *.ics files")
    check.add_argument("--strict", action="store_true",
                       help="treat warnings as failures too (exit 1)")
    check.add_argument("--format", choices=("text", "json"), default="text",
                       help="output format (default: text)")
    return p


def _collect_files(path: str):
    """Resolve the path argument to a list of files to check.

    Returns None if the path does not exist.
    """
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        found = []
        for root, _dirs, names in os.walk(path):
            for name in names:
                if name.lower().endswith(".ics"):
                    found.append(os.path.join(root, name))
        return sorted(found)
    return None


def _run_check(args) -> int:
    files = _collect_files(args.path)
    if files is None:
        print(f"icslint: no such file or folder: {args.path}", file=sys.stderr)
        return 2
    if not files:
        print(f"icslint: no .ics files found under {args.path}")
        return 0
    findings = []
    for path in files:
        try:
            findings.extend(lint_file(path))
        except OSError as exc:
            print(f"icslint: cannot read {path}: {exc.strerror or exc}",
                  file=sys.stderr)
            return 2
    findings.sort(key=lambda f: f.sort_key())
    errors = sum(1 for f in findings if f.severity == "ERROR")
    warnings = sum(1 for f in findings if f.severity == "WARNING")
    if args.format == "json":
        payload = {
            "files_checked": len(files),
            "errors": errors,
            "warnings": warnings,
            "findings": [
                {
                    "file": f.file,
                    "line": f.line,
                    "rule": f.rule,
                    "severity": f.severity,
                    "component": f.component,
                    "message": f.message,
                    "source": f.source,
                    "source_type": f.source_type,
                }
                for f in findings
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        for f in findings:
            print(f"{f.file}:{f.line}: {f.severity} {f.rule} "
                  f"[{f.component}] {f.message} ({f.source})")
        n = len(files)
        if findings:
            print(f"icslint: {n} file{'s' if n != 1 else ''} checked, "
                  f"{errors} error{'s' if errors != 1 else ''}, "
                  f"{warnings} warning{'s' if warnings != 1 else ''}")
        else:
            print(f"icslint: {n} file{'s' if n != 1 else ''} checked, "
                  "no findings")
    if errors or (args.strict and warnings):
        return 1
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return _run_check(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
