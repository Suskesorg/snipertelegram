#!/usr/bin/env python3
"""Filter credentials out of anything on its way to a terminal, log, or file.

    curl -s "$SOME_RPC" ... | python3 scripts/redact_stream.py
    python3 scripts/redact_stream.py < raw.json > safe.json
    python3 scripts/redact_stream.py --check < report.md   # exit 1 if a secret is present

Reads standard input, writes redacted standard output. Values of environment
variables whose names look like credentials are replaced by name, query
parameters and auth headers are blanked, and any URL is reduced to a form that
cannot be replayed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Piping into head or less should end the script quietly, not with a traceback.
try:
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except (AttributeError, ValueError, ImportError):  # not available on Windows
    pass
from rhclib import redact  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="report whether a raw credential is present, change nothing")
    args = parser.parse_args()

    text = sys.stdin.read()
    secrets = redact.collect_env_secrets()

    if args.check:
        found = sorted({name for value, name in secrets.items() if value and value in text})
        if found:
            print("credential values present from: %s" % ", ".join(found), file=sys.stderr)
            return 1
        print("no raw credential values found", file=sys.stderr)
        return 0

    sys.stdout.write(redact.redact_text(text, secrets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
