"""Helper library for the robinhood-chain-research-analyst skill.

Standard library only. Import from a script with:

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from rhclib import config, crypto, evidence, health, net, redact
"""

__all__ = ["config", "crypto", "evidence", "health", "jsonschema_min", "net", "redact"]
__version__ = "1.0.0"
