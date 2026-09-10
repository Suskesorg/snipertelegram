#!/usr/bin/env python3
"""Validate a configuration file and show what the analyst will actually do.

    python3 scripts/validate_config.py
    python3 scripts/validate_config.py --config robinhood-chain.config.yaml
    python3 scripts/validate_config.py --json

Prints which credential slots are configured, by variable name and never by
value. Exits 0 when the configuration is usable, 1 when it is not.
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
from rhclib import redact  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", help="path to a configuration file")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    try:
        settings, source = cfglib.load_config(args.config)
    except cfglib.ConfigError as exc:
        print("Configuration could not be read: %s" % exc, file=sys.stderr)
        return 1

    errors = cfglib.validate_config(settings)
    env_rows = cfglib.env_report(settings)
    endpoint_url, endpoint_source = cfglib.endpoint(settings, "primary_rpc")

    if args.json:
        print(json.dumps({
            "source": str(source) if source else None,
            "valid": not errors,
            "errors": errors,
            "environment": env_rows,
            "primary_rpc": {
                "endpoint": redact.safe_endpoint(endpoint_url) if endpoint_url else None,
                "from": endpoint_source,
            },
            "effective": redact.redact_obj(settings),
        }, indent=2))
        return 0 if not errors else 1

    print("Configuration file : %s" % (source or "(built-in defaults)"))
    if source and Path(source).name == "config.example.yaml":
        print("                     using the shipped example. Copy it before editing.")
    print("Network            : %s %s, expecting chain id %s"
          % (settings["network"].get("name"), settings["network"].get("environment"),
             settings["network"].get("expected_chain_id")))
    print("Mode / posture     : %s, %s, audience %s"
          % (settings["analyst"].get("default_mode"), settings["analyst"].get("risk_posture"),
             settings["analyst"].get("audience")))
    print("Focus areas        : %s" % ", ".join(settings["research"].get("focus", [])))
    print("Exit sizes (USD)   : %s" % ", ".join(str(s) for s in settings["research"].get("exit_sizes_usd", [])))
    print("First-pass budget  : %s requests, %s operations, %s minutes, %s retries per check"
          % (settings["research"].get("max_initial_provider_requests"),
             settings["research"].get("max_initial_provider_operations"),
             settings["research"].get("max_initial_runtime_minutes"),
             settings["research"].get("max_failed_attempts_per_check")))
    print("Evidence rules     : block pin=%s, address binding=%s, dashboard-only=%s, keep raw=%s"
          % (settings["evidence"].get("require_block_pin"),
             settings["evidence"].get("require_exact_address_binding"),
             settings["evidence"].get("allow_dashboard_only_claims"),
             settings["evidence"].get("preserve_raw_evidence")))
    print("Primary RPC        : %s  (from %s)"
          % (redact.safe_endpoint(endpoint_url) if endpoint_url else "(none)", endpoint_source))

    print("\nCredential slots (names only, values are never read into output):")
    for row in env_rows:
        mark = "set" if row["configured"] else "unset"
        print("  %-24s %-32s %-5s %s"
              % (row["slot"], row["env_var"], mark, row["value_shape"]))

    unset_required = [r for r in env_rows if r["slot"] == "primary_rpc" and not r["configured"]]
    if unset_required and settings["providers"].get("use_public_rpc_fallback", True):
        print("\n  No RPC variable is set. Starter mode will use the public endpoint above.")

    for template_key, key_slot, label in (
            ("alchemy_url_template", "alchemy_key", "Alchemy"),
            ("drpc_url_template", "drpc_key", "dRPC")):
        has_key = any(r["slot"] == key_slot and r["configured"] for r in env_rows)
        if has_key and not settings["providers"].get(template_key):
            print("\n  %s credential is set but providers.%s is empty. Look up the current "
                  "endpoint format in %s's own documentation and fill it in; the helpers "
                  "will not guess a URL." % (label, template_key, label))

    if errors:
        print("\nProblems to fix (%d):" % len(errors))
        for item in errors:
            print("  - %s" % item)
        return 1
    print("\nConfiguration is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
