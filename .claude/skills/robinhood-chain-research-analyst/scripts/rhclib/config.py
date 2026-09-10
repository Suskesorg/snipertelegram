"""Configuration loading, defaults, validation, and environment resolution.

Design notes worth knowing before changing this file:

* PyYAML is used when it is installed, and a small indentation parser covering
  the shapes in `config.example.yaml` is used when it is not. A research helper
  that refuses to start because of a missing dependency is a helper nobody
  runs, and the config file is deliberately simple enough to parse safely.
* Environment variables are resolved by *name*, and only their presence is ever
  reported. No function here returns a credential value to a caller that
  prints things.
* Nothing in this module reads a credential from a file. Credentials come from
  the environment only, which is what keeps them out of commits.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import redact

SKILL_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = SKILL_ROOT / "config.example.yaml"
CONFIG_SCHEMA = SKILL_ROOT / "schemas" / "config.schema.json"

#: Where a user config may live, in priority order. The example config is the
#: last resort so the helpers always have a complete set of defaults.
SEARCH_PATHS = (
    "robinhood-chain.config.yaml",
    "robinhood-chain.config.yml",
    ".robinhood-chain.yaml",
    "~/.config/robinhood-chain-research-analyst/config.yaml",
)

#: Baked-in defaults. These mirror config.example.yaml so that a partial user
#: config still produces a complete, valid configuration.
DEFAULTS = {
    "analyst": {
        "style": "concise",
        "risk_posture": "conservative",
        "default_mode": "focused",
        "audience": "informed_retail",
        "language": "en",
    },
    "network": {
        "name": "Robinhood Chain",
        "environment": "mainnet",
        "expected_chain_id": 4663,
        "verify_chain_id_before_use": True,
        "verify_documentation_before_use": True,
        "allow_environment_switch": "never_silently",
    },
    "research": {
        "focus": [
            "identity_and_source",
            "contract_controls",
            "proxy_and_upgrade_risk",
            "liquidity_custody",
            "sellability_and_exit_depth",
            "holder_concentration",
            "fees_and_treasury",
            "rwa_rights_and_redemption",
            "external_dependencies",
        ],
        "exit_sizes_usd": [1000, 10000, 100000],
        "include_historical_launch_analysis": "when_triggered",
        "max_initial_runtime_minutes": 10,
        "max_initial_provider_requests": 30,
        "max_initial_provider_operations": 100,
        "max_failed_attempts_per_check": 2,
        "pons_default_selection": "require_address",
        "sentiment_window_hours": 72,
        "social_sample_limit": 200,
        "report_depth": "standard",
        "log_block_range_limit": 10000,
    },
    "evidence": {
        "require_block_pin": True,
        "require_exact_address_binding": True,
        "allow_dashboard_only_claims": False,
        "preserve_raw_evidence": True,
        "raw_evidence_dir": "./research/raw",
        "min_sources_for_proven": 1,
        "min_sources_for_strongly_supported": 2,
    },
    "providers": {
        "primary_rpc_env": "ROBINHOOD_RPC_URL",
        "archive_rpc_env": "ROBINHOOD_ARCHIVE_RPC_URL",
        "secondary_rpc_env": "ROBINHOOD_SECONDARY_RPC_URL",
        "use_public_rpc_fallback": True,
        "public_rpc_url": "https://rpc.mainnet.chain.robinhood.com",
        "public_rpc_url_testnet": "https://rpc.testnet.chain.robinhood.com",
        "blockscout_url": "https://robinhoodchain.blockscout.com",
        "blockscout_url_testnet": "https://explorer.testnet.chain.robinhood.com",
        "geckoterminal_url": "https://api.geckoterminal.com/api/v2",
        "geckoterminal_network_id": "",
        "coingecko_key_env": "COINGECKO_API_KEY",
        "coingecko_public_url": "https://api.coingecko.com/api/v3",
        "coingecko_pro_url": "https://pro-api.coingecko.com/api/v3",
        "defillama_key_env": "DEFILLAMA_API_KEY",
        "defillama_public_url": "https://api.llama.fi",
        "alchemy_key_env": "ALCHEMY_API_KEY",
        "alchemy_url_template": "",
        "drpc_url_env": "DRPC_URL",
        "drpc_key_env": "DRPC_API_KEY",
        "drpc_url_template": "",
        "x_bearer_env": "X_BEARER_TOKEN",
        "traditional_market_data_env": "TRADITIONAL_MARKET_DATA_API_KEY",
        "traditional_market_data_url": "",
        "request_timeout_seconds": 20,
        "env_aliases": {},
    },
    "output": {
        "write_reports_to": "./research",
        "include_evidence_appendix": True,
        "include_provider_health": True,
        "redact_endpoints_in_reports": True,
    },
}

#: Logical provider slots mapped to the config key naming their env variable.
#: Used to resolve aliases without hard-coding brand names in the helpers.
ENV_SLOTS = {
    "primary_rpc": "primary_rpc_env",
    "archive_rpc": "archive_rpc_env",
    "secondary_rpc": "secondary_rpc_env",
    "alchemy_key": "alchemy_key_env",
    "drpc_url": "drpc_url_env",
    "drpc_key": "drpc_key_env",
    "coingecko_key": "coingecko_key_env",
    "defillama_key": "defillama_key_env",
    "x_bearer": "x_bearer_env",
    "traditional_market_data": "traditional_market_data_env",
}


class ConfigError(Exception):
    pass


# --------------------------------------------------------------------------
# YAML loading
# --------------------------------------------------------------------------

def load_yaml(text: str) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        return _mini_yaml(text)
    loaded = yaml.safe_load(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError("the configuration file must be a mapping at the top level")
    return loaded


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for index, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (index == 0 or line[index - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(text: str):
    text = text.strip()
    if text == "" or text in ("~", "null", "Null", "NULL"):
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(part) for part in _split_top(inner)] if inner else []
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        if not inner:
            return {}
        out = {}
        for part in _split_top(inner):
            key, _, value = part.partition(":")
            out[key.strip()] = _scalar(value)
        return out
    lowered = text.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d*\.\d+", text):
        return float(text)
    return text


def _split_top(text: str) -> list:
    parts, depth, quote, current = [], 0, None, []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip() != ""]


def _mini_yaml(text: str) -> dict:
    """Parse the block-mapping / block-sequence subset used by the example config.

    Anything outside that subset raises with the offending line number and a
    pointer to PyYAML, rather than guessing at the intent. Guessing is how a
    config silently means something other than what its author wrote.
    """
    tokens = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw)
        if not line.strip() or line.strip().startswith("---"):
            continue
        tokens.append((number, len(line) - len(line.lstrip(" ")), line.strip()))
    if not tokens:
        return {}
    value, index = _parse_block(tokens, 0, tokens[0][1])
    if index != len(tokens):
        raise ConfigError("line %d: indentation does not line up with any parent key."
                          % tokens[index][0])
    if not isinstance(value, dict):
        raise ConfigError("the configuration file must be a mapping at the top level")
    return value


def _parse_block(tokens, index, indent):
    if tokens[index][2].startswith("- "):
        return _parse_sequence(tokens, index, indent)
    return _parse_mapping(tokens, index, indent)


def _parse_sequence(tokens, index, indent):
    items = []
    while index < len(tokens):
        number, line_indent, body = tokens[index]
        if line_indent < indent or not body.startswith("- "):
            break
        if line_indent > indent:
            raise ConfigError("line %d: unexpected indentation inside a list." % number)
        item = body[2:].strip()
        if ":" in item and not item.startswith(("\"", "'", "[", "{")):
            raise ConfigError("line %d: lists of mappings need PyYAML (pip install pyyaml)." % number)
        items.append(_scalar(item))
        index += 1
    return items, index


def _parse_mapping(tokens, index, indent):
    out = {}
    while index < len(tokens):
        number, line_indent, body = tokens[index]
        if line_indent < indent or body.startswith("- "):
            break
        if line_indent > indent:
            raise ConfigError("line %d: unexpected indentation." % number)
        key, separator, value = body.partition(":")
        if not separator:
            raise ConfigError("line %d: expected 'key: value'. Install PyYAML for full YAML support."
                              % number)
        key = key.strip().strip("\"'")
        value = value.strip()
        index += 1
        if value != "":
            out[key] = _scalar(value)
            continue
        if index < len(tokens) and tokens[index][1] > indent:
            out[key], index = _parse_block(tokens, index, tokens[index][1])
        elif index < len(tokens) and tokens[index][1] == indent and tokens[index][2].startswith("- "):
            out[key], index = _parse_sequence(tokens, index, indent)
        else:
            out[key] = {}
    return out, index


# --------------------------------------------------------------------------
# Loading and merging
# --------------------------------------------------------------------------

def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def find_config(explicit=None):
    """Return the path the configuration should be read from, or None."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise ConfigError("configuration file not found: %s" % path)
        return path
    from_env = os.environ.get("ROBINHOOD_CHAIN_ANALYST_CONFIG")
    if from_env:
        path = Path(from_env).expanduser()
        if not path.exists():
            raise ConfigError("ROBINHOOD_CHAIN_ANALYST_CONFIG points at a missing file: %s" % path)
        return path
    for candidate in SEARCH_PATHS:
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    if EXAMPLE_CONFIG.exists():
        return EXAMPLE_CONFIG
    return None


def load_config(explicit=None):
    """Return (config, source_path). Defaults fill anything the file omits."""
    path = find_config(explicit)
    if path is None:
        return (json.loads(json.dumps(DEFAULTS)), None)
    user = load_yaml(Path(path).read_text(encoding="utf-8"))
    return (deep_merge(DEFAULTS, user), Path(path))


def load_schema():
    if not CONFIG_SCHEMA.exists():
        raise ConfigError("config schema missing at %s" % CONFIG_SCHEMA)
    return json.loads(CONFIG_SCHEMA.read_text(encoding="utf-8"))


def validate_config(config: dict) -> list:
    from . import jsonschema_min
    errors = jsonschema_min.validate(config, load_schema())
    errors.extend(cross_field_errors(config))
    return errors


def cross_field_errors(config: dict) -> list:
    """Checks a schema cannot express, mostly about not mixing up networks."""
    errors = []
    network = config.get("network", {})
    environment = network.get("environment")
    chain_id = network.get("expected_chain_id")
    known = {"mainnet": 4663, "testnet": 46630}
    if environment in known and isinstance(chain_id, int) and chain_id != known[environment]:
        errors.append(
            "network: environment %r is seeded with chain id %d, but expected_chain_id is %s. "
            "Change one deliberately, and confirm against current official documentation before use."
            % (environment, known[environment], chain_id))
    evidence = config.get("evidence", {})
    if evidence.get("allow_dashboard_only_claims") and evidence.get("require_block_pin"):
        errors.append(
            "evidence: allow_dashboard_only_claims is true while require_block_pin is true. "
            "Aggregator dashboards do not carry a block pin, so these two settings contradict.")
    research = config.get("research", {})
    sizes = research.get("exit_sizes_usd")
    if isinstance(sizes, list) and sizes != sorted(sizes):
        errors.append("research.exit_sizes_usd: list ascending so exit depth reads in order")
    minimum = evidence.get("min_sources_for_proven")
    stronger = evidence.get("min_sources_for_strongly_supported")
    if isinstance(minimum, int) and isinstance(stronger, int) and stronger < minimum:
        errors.append("evidence: min_sources_for_strongly_supported is below min_sources_for_proven")
    return errors


# --------------------------------------------------------------------------
# Environment resolution
# --------------------------------------------------------------------------

def env_name(config: dict, slot: str) -> str:
    """Resolve a logical slot to the environment variable name to read.

    `providers.env_aliases` lets a user point a slot at whatever variable they
    already have, which is the supported way to bring your own naming.
    """
    providers = config.get("providers", {})
    aliases = providers.get("env_aliases") or {}
    if slot in aliases:
        return str(aliases[slot])
    key = ENV_SLOTS.get(slot)
    default = DEFAULTS["providers"].get(key, "") if key else ""
    name = providers.get(key, default) if key else ""
    if name in aliases:
        return str(aliases[name])
    return str(name or "")


def env_value(config: dict, slot: str):
    """Read a credential value. Callers must never print the result."""
    name = env_name(config, slot)
    return os.environ.get(name) if name else None


def env_report(config: dict) -> list:
    """Presence-only report of every credential slot, safe to print."""
    rows = []
    for slot in ENV_SLOTS:
        name = env_name(config, slot)
        value = os.environ.get(name) if name else None
        rows.append({
            "slot": slot,
            "env_var": name or "(unmapped)",
            "configured": bool(value),
            "value_shape": _shape(value),
        })
    return rows


def _shape(value):
    """Describe a credential without revealing it: length and character class."""
    if not value:
        return "unset"
    kind = "url" if "://" in value else "opaque"
    return "%s, %d chars" % (kind, len(value))


def endpoint(config: dict, slot: str):
    """Return (url, source) for an RPC slot, honouring the public fallback."""
    providers = config.get("providers", {})
    value = env_value(config, slot)
    if value:
        return (value, env_name(config, slot))
    if slot == "primary_rpc" and providers.get("use_public_rpc_fallback", True):
        environment = config.get("network", {}).get("environment", "mainnet")
        key = "public_rpc_url" if environment == "mainnet" else "public_rpc_url_testnet"
        return (providers.get(key) or "", "config.providers.%s" % key)
    return (None, None)


def describe_endpoint(url) -> str:
    return redact.safe_endpoint(url) if url else "(not configured)"
