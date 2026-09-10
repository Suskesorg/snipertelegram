#!/usr/bin/env python3
"""Check which research capabilities are actually usable right now.

    python3 scripts/check_providers.py                     # probe live hosts
    python3 scripts/check_providers.py --json
    python3 scripts/check_providers.py --offline --fixture fixtures/provider_health_mixed.json

Every provider gets one of four states:

    available                 the host answered and the capability worked
    reachable_but_restricted  the host answered and refused, throttled, or
                              challenged us
    chain_mismatch            the host answered about a different chain
    unavailable               no usable answer, or nothing configured

The middle two exist because a 401, a 429 and a bot-protection page are proof
that a host is up and gating us. That is a limit on the run, and the report has
to say so. It is never a finding about the thing being researched.

This is an infrastructure check. It reads nothing about any target address.
Exit codes: 0 when current onchain state is readable, 2 when it is not.
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

STATE_MARK = {
    health.AVAILABLE: "OK  ",
    health.RESTRICTED: "GATE",
    health.CHAIN_MISMATCH: "CHAIN",
    health.UNAVAILABLE: "DOWN",
}


def build_probes(settings: dict) -> list:
    """Describe every probe without performing any of them.

    Probes are capability-first: what a provider is for matters, its brand does
    not. That is also why the credentialed providers carry a url_template the
    user fills in from current documentation instead of a guessed URL.
    """
    providers = settings.get("providers", {})
    environment = settings.get("network", {}).get("environment", "mainnet")
    testnet = environment == "testnet"
    probes = []

    primary_url, primary_source = cfglib.endpoint(settings, "primary_rpc")
    probes.append({
        "name": "primary_rpc", "capability": "current_onchain_state", "kind": "rpc",
        "url": primary_url, "env_var": cfglib.env_name(settings, "primary_rpc"),
        "optional": False, "source": primary_source,
    })
    probes.append({
        "name": "archive_rpc", "capability": "historical_state", "kind": "rpc",
        "url": cfglib.env_value(settings, "archive_rpc"),
        "env_var": cfglib.env_name(settings, "archive_rpc"), "optional": True,
    })
    probes.append({
        "name": "secondary_rpc", "capability": "independent_corroboration", "kind": "rpc",
        "url": cfglib.env_value(settings, "secondary_rpc"),
        "env_var": cfglib.env_name(settings, "secondary_rpc"), "optional": True,
    })

    for name, key_slot, template_key, env_hint in (
            ("alchemy", "alchemy_key", "alchemy_url_template", "alchemy_key"),
            ("drpc", "drpc_key", "drpc_url_template", "drpc_key")):
        url = None
        note = None
        if name == "drpc":
            url = cfglib.env_value(settings, "drpc_url")
        if not url:
            template = providers.get(template_key) or ""
            key = cfglib.env_value(settings, key_slot)
            if template and key:
                url = template.replace("{key}", key)
            elif key and not template:
                note = ("credential is set but providers.%s is empty. Look up the current "
                        "endpoint format in the provider's documentation and fill it in; "
                        "this helper will not guess a URL." % template_key)
        probes.append({
            "name": name, "capability": "enhanced_rpc", "kind": "rpc", "url": url,
            "env_var": cfglib.env_name(settings, env_hint), "optional": True, "note": note,
        })

    blockscout = providers.get("blockscout_url_testnet" if testnet else "blockscout_url")
    probes.append({
        "name": "blockscout", "capability": "contract_discovery_and_source", "kind": "rest",
        "url": _join(blockscout, "/api/v2/stats"), "base": blockscout, "optional": True,
        "env_var": "", "alt_paths": ["/api/v2/config/backend-version", "/api?module=block&action=eth_block_number"],
    })

    gecko_base = providers.get("geckoterminal_url")
    network_id = (providers.get("geckoterminal_network_id") or "").strip()
    probes.append({
        "name": "geckoterminal", "capability": "dex_pool_discovery", "kind": "rest",
        "url": _join(gecko_base, "/networks/%s" % network_id) if network_id else _join(gecko_base, "/networks"),
        "base": gecko_base, "optional": True, "env_var": "",
        "coverage_key": network_id or None,
        "note": None if network_id else ("providers.geckoterminal_network_id is empty, so only "
                                         "reachability is checked. Read this chain's id from the "
                                         "network list before binding any pool to it."),
    })

    coingecko_key = cfglib.env_value(settings, "coingecko_key")
    probes.append({
        "name": "coingecko_pro" if coingecko_key else "coingecko_public",
        "capability": "market_context", "kind": "rest",
        "url": _join(providers.get("coingecko_pro_url") if coingecko_key
                     else providers.get("coingecko_public_url"), "/ping"),
        "headers": {"x-cg-pro-api-key": coingecko_key} if coingecko_key else {},
        "optional": True, "env_var": cfglib.env_name(settings, "coingecko_key"),
    })

    defillama_key = cfglib.env_value(settings, "defillama_key")
    probes.append({
        "name": "defillama_pro" if defillama_key else "defillama_public",
        "capability": "protocol_context", "kind": "rest",
        "url": _join(providers.get("defillama_public_url"), "/v2/chains"),
        "headers": {"Authorization": "Bearer %s" % defillama_key} if defillama_key else {},
        "optional": True, "env_var": cfglib.env_name(settings, "defillama_key"),
        "coverage_key": settings.get("network", {}).get("name", "Robinhood"),
    })

    probes.append({
        "name": "x_api", "capability": "social_sampling", "kind": "social",
        "url": None, "optional": True, "env_var": cfglib.env_name(settings, "x_bearer"),
        "configured": bool(cfglib.env_value(settings, "x_bearer")),
    })
    probes.append({
        "name": "traditional_market_data", "capability": "reference_market_data", "kind": "rest",
        "url": providers.get("traditional_market_data_url") or None, "optional": True,
        "env_var": cfglib.env_name(settings, "traditional_market_data"),
    })
    return probes


def _join(base, path):
    if not base:
        return None
    return base.rstrip("/") + path


def outcome_from_fixture(entry: dict):
    """Rebuild a transport outcome from a recorded fixture, so classification
    can be exercised with no network at all."""
    body = entry.get("body")
    head = json.dumps(body) if body is not None else entry.get("body_text", "")
    content_type = entry.get("content_type", "application/json" if body is not None else "text/html")
    outcome = net.HttpOutcome(
        status=entry.get("status"),
        error_kind=entry.get("error_kind"),
        head=head,
        content_type=content_type,
        retry_after=entry.get("retry_after"),
        latency_ms=entry.get("latency_ms", 0),
    )
    return outcome


def run_probe(probe, settings, budget, fixtures=None, probe_social=False):
    expected = settings.get("network", {}).get("expected_chain_id")
    timeout = settings.get("providers", {}).get("request_timeout_seconds", 20)
    name = probe["name"]

    if probe["kind"] == "social" and not probe_social:
        record = health.unconfigured(name, probe["capability"], probe.get("env_var"))
        if probe.get("configured"):
            record["reason"] = "not_probed_by_default"
            record["notes"] = [
                "A bearer token is configured. Social endpoints are not probed by default "
                "because a probe spends search quota; pass --probe-social to check it.",
                "Until it is probed, treat social coverage as unproven.",
            ]
        else:
            record["notes"].append(
                "Without a bearer token, public web results are search-visible narrative, "
                "not a representative sample of sentiment. Label them that way.")
        return record

    if not probe.get("url"):
        record = health.unconfigured(name, probe["capability"], probe.get("env_var"),
                                     optional=probe.get("optional", True))
        if probe.get("note"):
            record["notes"].append(probe["note"])
        return record

    if fixtures is not None:
        entry = fixtures.get(name)
        if entry is None:
            record = health.unconfigured(name, probe["capability"], probe.get("env_var"))
            record["reason"] = "no_fixture"
            record["notes"] = ["Offline run: no fixture recorded for this probe."]
            return record
        outcome = outcome_from_fixture(entry)
    elif probe["kind"] == "rpc":
        outcome, _ = net.json_rpc(probe["url"], "eth_chainId", timeout=timeout, budget=budget)
    else:
        outcome = net.http_request(probe["url"], headers=probe.get("headers") or {},
                                   timeout=timeout, budget=budget, max_body_bytes=1 << 18)

    notes = []
    if probe.get("note"):
        notes.append(probe["note"])

    if probe["kind"] == "rpc":
        state, reason, observed = health.classify_rpc(outcome, expected)
        return health.record(name, probe["capability"], probe["url"], state, reason,
                             outcome=outcome, observed_chain_id=observed, notes=notes)

    state, reason = health.classify_http(outcome)
    observed = None
    coverage_key = probe.get("coverage_key")
    if state == health.AVAILABLE and coverage_key:
        state, reason = health.classify_rest_coverage(outcome.json(), coverage_key)
    elif state == health.UNAVAILABLE and reason.startswith("http_404") and coverage_key:
        state, reason = health.CHAIN_MISMATCH, "provider_does_not_list_network_%s" % coverage_key
    if state == health.UNAVAILABLE and reason.startswith("http_404") and probe.get("alt_paths"):
        notes.append("Endpoint path not found. Other paths to try on this host: %s"
                     % ", ".join(probe["alt_paths"]))
    return health.record(name, probe["capability"], probe["url"], state, reason,
                         outcome=outcome, observed_chain_id=observed, notes=notes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--offline", action="store_true",
                        help="classify recorded fixtures instead of contacting hosts")
    parser.add_argument("--fixture", help="fixture file for --offline")
    parser.add_argument("--probe-social", action="store_true",
                        help="also probe the social API, which spends search quota")
    parser.add_argument("--only", help="comma-separated probe names")
    args = parser.parse_args()

    settings, source = cfglib.load_config(args.config)
    errors = cfglib.validate_config(settings)
    if errors:
        print("Refusing to probe with an invalid configuration:", file=sys.stderr)
        for item in errors:
            print("  - %s" % item, file=sys.stderr)
        return 1

    fixtures = None
    if args.offline:
        if not args.fixture:
            print("--offline needs --fixture", file=sys.stderr)
            return 1
        fixtures = json.loads(Path(args.fixture).read_text(encoding="utf-8")).get("responses", {})

    research = settings.get("research", {})
    budget = net.RequestBudget(
        max_requests=research.get("max_initial_provider_requests", 30),
        max_operations=research.get("max_initial_provider_operations", 100),
        max_failures_per_check=research.get("max_failed_attempts_per_check", 2))

    wanted = {n.strip() for n in args.only.split(",")} if args.only else None
    records = []
    for probe in build_probes(settings):
        if wanted and probe["name"] not in wanted:
            continue
        try:
            records.append(run_probe(probe, settings, budget, fixtures, args.probe_social))
        except net.BudgetExceeded as exc:
            records.append(health.record(probe["name"], probe["capability"], probe.get("url"),
                                         health.UNAVAILABLE, "budget_exhausted",
                                         notes=[str(exc)]))
            break

    summary = health.summarise(records)
    payload = {
        "mode": "offline_fixture" if args.offline else "live_infrastructure_check",
        "config_source": str(source) if source else None,
        "network": {
            "environment": settings["network"].get("environment"),
            "expected_chain_id": settings["network"].get("expected_chain_id"),
        },
        "checked_at": net.now_iso(),
        "summary": summary,
        "providers": records,
        "budget": budget.snapshot(),
    }

    if args.json:
        print(json.dumps(redact.redact_obj(payload), indent=2))
    else:
        print("Provider check (%s) - %s, expecting chain id %s"
              % (payload["mode"], payload["network"]["environment"],
                 payload["network"]["expected_chain_id"]))
        print("-" * 78)
        for entry in records:
            print("%-5s %-24s %-30s %s"
                  % (STATE_MARK.get(entry["state"], "?"), entry["probe"],
                     entry["capability"], entry["reason"]))
            print("      %s" % entry["endpoint"])
            for note in entry["notes"]:
                print("      note: %s" % note)
        print("-" * 78)
        print("Tier: %s   onchain state readable: %s"
              % (summary["tier"], "yes" if summary["onchain_state_readable"] else "NO"))
        for line in summary["blocking"]:
            print("BLOCKING: %s" % line)
        print("Requests used: %d of %d" % (budget.requests, budget.max_requests))

    return 0 if summary["onchain_state_readable"] else 2


if __name__ == "__main__":
    sys.exit(main())
