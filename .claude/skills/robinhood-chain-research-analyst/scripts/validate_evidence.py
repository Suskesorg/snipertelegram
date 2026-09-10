#!/usr/bin/env python3
"""Check a report bundle against the skill's evidence rules before it is shown.

    python3 scripts/validate_evidence.py research/report.json
    python3 scripts/validate_evidence.py research/report.json --config my.yaml --json

It answers one question: does this report claim more than its evidence earns?
Errors mean it does. Warnings mean it is publishable but thinner than the
configuration asked for.

Exit codes: 0 clean, 1 errors, 0 with warnings only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Piping into head or less should end the script quietly, not with a traceback.
try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError, ImportError):  # not available on Windows
    pass
from rhclib import config as cfglib  # noqa: E402
from rhclib import evidence as evidencelib  # noqa: E402
from rhclib import redact  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", help="path to a report bundle JSON file")
    parser.add_argument("--config")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args()

    settings, _ = cfglib.load_config(args.config)
    path = Path(args.bundle)
    if not path.exists():
        print("bundle not found: %s" % path, file=sys.stderr)
        return 1
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print("bundle is not valid JSON: %s" % exc, file=sys.stderr)
        return 1

    result = evidencelib.validate_bundle(bundle, settings)
    summary = evidencelib.summarise(bundle)

    leaked = []
    serialised = json.dumps(bundle)
    for value, name in redact.collect_env_secrets().items():
        if value and value in serialised:
            leaked.append(name)
    if leaked:
        result["errors"].append(
            "the bundle contains the value of %s. Credentials must never reach a report or a "
            "cached artifact." % ", ".join(sorted(leaked)))

    if args.json:
        print(json.dumps({"summary": summary, "errors": result["errors"],
                          "warnings": result["warnings"]}, indent=2))
    else:
        print("Bundle      : %s" % path)
        print("Findings    : %d (%s)" % (summary["findings"], ", ".join(
            "%s %d" % (k, v) for k, v in summary["by_confidence"].items() if v)))
        print("Evidence    : %d records" % summary["evidence"])
        print("Limitations : %d disclosed" % summary["coverage_limitations"])
        if result["errors"]:
            print("\nErrors (%d) - the report claims more than it shows:" % len(result["errors"]))
            for item in result["errors"]:
                print("  - %s" % item)
        if result["warnings"]:
            print("\nWarnings (%d):" % len(result["warnings"]))
            for item in result["warnings"]:
                print("  - %s" % item)
        if not result["errors"] and not result["warnings"]:
            print("\nEvery finding is supported at the confidence it claims.")
        elif not result["errors"]:
            print("\nNo errors. Findings are supported at the confidence they claim.")

    if result["errors"]:
        return 1
    if args.strict and result["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
