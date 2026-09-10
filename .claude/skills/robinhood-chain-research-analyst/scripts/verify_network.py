#!/usr/bin/env python3
"""Pin the network before any research claim is made.

    python3 scripts/verify_network.py
    python3 scripts/verify_network.py --json
    python3 scripts/verify_network.py --compare      # also read the secondary RPC

Reads eth_chainId and the latest block from the configured endpoint, and
refuses to report success if the chain id is not the one in the configuration.
This is an infrastructure check: it asks the node about itself and about the
head of the chain, and nothing about any address.

Every later reading should be taken at the block this prints, so the whole
report speaks as of one moment.

Exit codes: 0 verified, 2 chain mismatch, 3 endpoint unusable.
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
from rhclib import health, net, redact  # noqa: E402


def read_head(url, timeout, budget, expected):
    outcome, payload = net.json_rpc(url, "eth_chainId", timeout=timeout, budget=budget)
    state, reason, observed = health.classify_rpc(outcome, expected)
    result = {
        "endpoint": redact.safe_endpoint(url),
        "host": redact.provider_label(url),
        "state": state,
        "reason": reason,
        "chain_id": observed,
        "observed_at": net.now_iso(),
        "block": None,
    }
    if state != health.AVAILABLE:
        return result

    outcome, payload = net.json_rpc(url, "eth_getBlockByNumber", ["latest", False],
                                    timeout=timeout, budget=budget)
    block = (payload or {}).get("result") if isinstance(payload, dict) else None
    if isinstance(block, dict):
        result["block"] = {
            "number": net.hex_to_int(block.get("number")),
            "hash": block.get("hash"),
            "timestamp_unix": net.hex_to_int(block.get("timestamp")),
            "parent_hash": block.get("parentHash"),
        }
    else:
        result["state"] = health.RESTRICTED
        result["reason"] = "latest_block_unavailable"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--compare", action="store_true",
                        help="also read the secondary endpoint and compare heads")
    args = parser.parse_args()

    settings, _ = cfglib.load_config(args.config)
    errors = cfglib.validate_config(settings)
    if errors:
        for item in errors:
            print("config: %s" % item, file=sys.stderr)
        return 1

    expected = settings["network"].get("expected_chain_id")
    timeout = settings["providers"].get("request_timeout_seconds", 20)
    budget = net.RequestBudget(
        max_requests=settings["research"].get("max_initial_provider_requests", 30),
        max_operations=settings["research"].get("max_initial_provider_operations", 100))

    url, source = cfglib.endpoint(settings, "primary_rpc")
    if not url:
        print("No RPC endpoint. Set %s or enable providers.use_public_rpc_fallback."
              % cfglib.env_name(settings, "primary_rpc"), file=sys.stderr)
        return 3

    primary = read_head(url, timeout, budget, expected)
    payload = {
        "check": "network_identity_and_head",
        "note": "Infrastructure check only. No target address was queried.",
        "network": {
            "name": settings["network"].get("name"),
            "environment": settings["network"].get("environment"),
            "expected_chain_id": expected,
        },
        "primary": primary,
        "endpoint_source": source,
    }

    if args.compare:
        secondary_url = cfglib.env_value(settings, "secondary_rpc")
        if secondary_url:
            secondary = read_head(secondary_url, timeout, budget, expected)
            payload["secondary"] = secondary
            payload["comparison"] = compare(primary, secondary)
        else:
            payload["secondary"] = {"state": health.UNAVAILABLE, "reason": "not_configured"}

    if args.json:
        print(json.dumps(redact.redact_obj(payload), indent=2))
    else:
        print("Network identity check (infrastructure only, no target queried)")
        print("  expected     : %s %s, chain id %s"
              % (payload["network"]["name"], payload["network"]["environment"], expected))
        print("  endpoint     : %s (from %s)" % (primary["endpoint"], source))
        print("  state        : %s (%s)" % (primary["state"], primary["reason"]))
        print("  chain id     : %s" % primary["chain_id"])
        if primary["block"]:
            print("  head block   : %s" % primary["block"]["number"])
            print("  head hash    : %s" % primary["block"]["hash"])
            print("  head time    : %s (unix)" % primary["block"]["timestamp_unix"])
            print("\n  Pin every reading in this run to block %s." % primary["block"]["number"])
        if "comparison" in payload:
            print("  second host  : %s" % payload["secondary"].get("host", "(none)"))
            for line in payload["comparison"]["notes"]:
                print("  compare      : %s" % line)

    if primary["state"] == health.CHAIN_MISMATCH:
        print("\nSTOP: this endpoint is not the configured network. Do not report its data as "
              "Robinhood Chain, and do not switch networks without saying so.", file=sys.stderr)
        return 2
    return 0 if primary["state"] == health.AVAILABLE else 3


def compare(primary, secondary) -> dict:
    """Two endpoints agreeing raises confidence; disagreeing is kept, not resolved."""
    notes = []
    if secondary.get("state") != health.AVAILABLE:
        return {"agree": None, "notes": ["secondary endpoint unusable (%s)" % secondary.get("reason")]}
    if primary.get("chain_id") != secondary.get("chain_id"):
        notes.append("chain ids differ: %s vs %s. These are different networks."
                     % (primary.get("chain_id"), secondary.get("chain_id")))
        return {"agree": False, "notes": notes}
    first = (primary.get("block") or {}).get("number")
    second = (secondary.get("block") or {}).get("number")
    if first is None or second is None:
        return {"agree": None, "notes": ["one endpoint did not return a head block"]}
    drift = abs(first - second)
    notes.append("head blocks %s and %s, drift %d block(s)" % (first, second, drift))
    if drift == 0 and (primary.get("block") or {}).get("hash") != (secondary.get("block") or {}).get("hash"):
        notes.append("same height, different hash: one endpoint is on a different fork. "
                     "Record both and do not merge their readings.")
        return {"agree": False, "notes": notes}
    if drift > 0:
        notes.append("read both at an explicit block number rather than 'latest' so the "
                     "comparison is like for like")
    return {"agree": drift <= 5, "notes": notes}


if __name__ == "__main__":
    sys.exit(main())
