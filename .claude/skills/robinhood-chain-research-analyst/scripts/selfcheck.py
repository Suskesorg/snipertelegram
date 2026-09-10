#!/usr/bin/env python3
"""Prove the skill's helpers work, without touching the network.

    python3 scripts/selfcheck.py
    python3 scripts/selfcheck.py --quiet

Runs the offline test suite and re-validates every shipped artifact: the
configuration example against its schema, both fixture bundles against the
evidence rules, and the provider health fixtures against the classifier.

No network access, no live investigation. Exit 0 when everything passes.
"""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError, ImportError):
    pass

from rhclib import config as cfglib  # noqa: E402
from rhclib import evidence as evidencelib  # noqa: E402
from rhclib import health  # noqa: E402


def check_artifacts(report) -> int:
    """Re-validate what ships, independently of the unit tests."""
    failures = 0

    settings, source = cfglib.load_config(str(ROOT / "config.example.yaml"))
    errors = cfglib.validate_config(settings)
    failures += _result(report, "config.example.yaml validates", not errors, errors)

    for name in ("config.schema.json", "evidence-record.schema.json",
                 "finding.schema.json", "report.schema.json"):
        path = ROOT / "schemas" / name
        ok = path.exists()
        detail = []
        if ok:
            try:
                evidencelib.load_schema(name)
            except Exception as exc:  # noqa: BLE001
                ok, detail = False, [str(exc)]
        failures += _result(report, "schema %s loads" % name, ok, detail)

    valid = json.loads((ROOT / "fixtures" / "report_valid.json").read_text(encoding="utf-8"))
    result = evidencelib.validate_bundle(valid, settings)
    failures += _result(report, "fixtures/report_valid.json passes the evidence rules",
                        not result["errors"], result["errors"])

    invalid = json.loads((ROOT / "fixtures" / "report_invalid.json").read_text(encoding="utf-8"))
    result = evidencelib.validate_bundle(invalid, settings)
    failures += _result(report, "fixtures/report_invalid.json is rejected",
                        len(result["errors"]) >= 15,
                        ["expected at least 15 errors, got %d" % len(result["errors"])]
                        if len(result["errors"]) < 15 else [])

    import check_providers
    states = set()
    fixtures = json.loads((ROOT / "fixtures" / "provider_health_mixed.json")
                          .read_text(encoding="utf-8"))["responses"]
    for probe in check_providers.build_probes(settings):
        entry = check_providers.run_probe(probe, settings, None, fixtures)
        states.add(entry["state"])
    missing = set(health.STATES) - states
    failures += _result(report, "all four provider states are produced by the fixtures",
                        not missing, ["never produced: %s" % ", ".join(sorted(missing))]
                        if missing else [])

    for name in ("SKILL.md", "config.example.yaml", "README.md"):
        failures += _result(report, "%s is present" % name, (ROOT / name).exists(), [])

    return failures


def _result(report, label, ok, detail):
    report("  %s %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        for line in detail or []:
            report("       %s" % line)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = (lambda *a: None) if args.quiet else print

    report("Offline test suite")
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT / "tests"))
    runner = unittest.TextTestRunner(verbosity=0 if args.quiet else 1,
                                     stream=sys.stdout if not args.quiet else open("/dev/null", "w"))
    outcome = runner.run(suite)

    report("\nShipped artifacts")
    artifact_failures = check_artifacts(report)

    total = len(outcome.failures) + len(outcome.errors) + artifact_failures
    report("\n%s  tests run %d, test failures %d, artifact failures %d"
           % ("ALL CHECKS PASSED" if total == 0 else "FAILURES PRESENT",
              outcome.testsRun, len(outcome.failures) + len(outcome.errors), artifact_failures))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
