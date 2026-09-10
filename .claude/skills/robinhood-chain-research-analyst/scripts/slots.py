#!/usr/bin/env python3
"""Print the selectors, event topics, and storage slots the playbooks use.

    python3 scripts/slots.py
    python3 scripts/slots.py --json
    python3 scripts/slots.py --selector "transfer(address,uint256)"
    python3 scripts/slots.py --slot "eip1967.proxy.implementation" --minus-one
    python3 scripts/slots.py --checksum 0x217339e01adaba70e8875791ff848abf44365671

Everything here is computed from its preimage rather than copied from memory,
so a wrong constant shows up as a wrong hash instead of as a quietly empty
storage read.
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
from rhclib import crypto  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--selector", help="function signature to hash")
    parser.add_argument("--topic", help="event signature to hash")
    parser.add_argument("--slot", help="preimage of a storage slot")
    parser.add_argument("--minus-one", action="store_true", help="use the EIP-1967 minus-one form")
    parser.add_argument("--checksum", help="address to checksum (EIP-55)")
    args = parser.parse_args()

    if args.selector:
        print(crypto.selector(args.selector))
        return 0
    if args.topic:
        print(crypto.event_topic(args.topic))
        return 0
    if args.slot:
        print(crypto.slot_minus_one(args.slot) if args.minus_one else crypto.slot_direct(args.slot))
        return 0
    if args.checksum:
        try:
            print(crypto.to_checksum_address(args.checksum))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    slots = crypto.proxy_slots()
    selectors = {sig: crypto.selector(sig) for sig in crypto.PROBE_CALLS}
    topics = {sig: crypto.event_topic(sig) for sig in crypto.CONTROL_EVENTS}

    if args.json:
        print(json.dumps({"proxy_slots": slots, "selectors": selectors, "event_topics": topics}, indent=2))
        return 0

    print("Proxy storage slots (read with eth_getStorageAt at a pinned block)")
    for name, entry in slots.items():
        print("  %-28s %s" % (name, entry["slot"]))
        print("  %-28s %s of %r" % ("", entry["derivation"], entry["preimage"]))
    print("\nRead-only probe calls (eth_call)")
    for signature, value in selectors.items():
        print("  %-10s %-34s %s" % (value, signature, crypto.PROBE_CALLS[signature]))
    print("\nControl event topics (eth_getLogs topic0)")
    for signature, value in topics.items():
        print("  %s  %s" % (value, signature))
    return 0


if __name__ == "__main__":
    sys.exit(main())
