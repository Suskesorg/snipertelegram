"""Provider health probing and classification.

The four states this module reports are the ones the skill's rules depend on:

  available                 the host answered and the capability worked
  reachable_but_restricted  the host answered and refused, throttled, or
                            challenged us; the capability is not proven usable
  chain_mismatch            the host answered about a different chain than the
                            one under investigation
  unavailable               no usable answer from the host at all

The distinction between the middle two and `unavailable` is the whole point. A
401, a 429 and a bot-protection page each prove a host is up and something is
gating us, which is a coverage limitation to disclose. Treating them as
"offline" would let a rate limit masquerade as a fact about the target, and
treating a chain mismatch as "available" would let another chain's data walk
into a Robinhood Chain report.

Classification is deliberately separated from transport so it can be tested
against recorded fixtures with no network access at all.
"""

from __future__ import annotations

from . import net, redact

AVAILABLE = "available"
RESTRICTED = "reachable_but_restricted"
CHAIN_MISMATCH = "chain_mismatch"
UNAVAILABLE = "unavailable"

STATES = (AVAILABLE, RESTRICTED, CHAIN_MISMATCH, UNAVAILABLE)

#: Markers that mean "a human-verification or edge layer answered, not the API".
CHALLENGE_MARKERS = (
    "just a moment", "cf-chl", "cf_chl", "checking your browser", "captcha",
    "attention required", "enable javascript and cookies", "ddos protection",
    "access denied", "request blocked", "are you a robot", "__cf_bm",
    "please verify you are a human",
)

_TRANSPORT_STATE = {
    "timeout": (UNAVAILABLE, "timeout"),
    "dns_failure": (UNAVAILABLE, "dns_failure"),
    "connect_error": (UNAVAILABLE, "connect_error"),
    "tls_error": (UNAVAILABLE, "tls_error"),
    "proxy_error": (UNAVAILABLE, "proxy_error"),
    "transport_error": (UNAVAILABLE, "transport_error"),
}

#: Reasons that describe our own egress path rather than the provider.
LOCAL_EGRESS_PREFIX = "proxy_denied_"


def looks_like_challenge(head: str, content_type: str = "") -> bool:
    lowered = (head or "").lower()
    if any(marker in lowered for marker in CHALLENGE_MARKERS):
        return True
    # An HTML page where JSON was requested is an edge layer far more often
    # than it is the API, so it is treated as gated rather than broken.
    return "html" in (content_type or "").lower() and "<html" in lowered


def classify_http(outcome) -> tuple:
    """Map a transport outcome to (state, reason). Reads no body content out
    to the caller: only the markers it needs for the decision."""
    if outcome.error_kind:
        if outcome.error_kind.startswith(LOCAL_EGRESS_PREFIX):
            return (RESTRICTED, outcome.error_kind)
        return _TRANSPORT_STATE.get(outcome.error_kind, (UNAVAILABLE, outcome.error_kind))

    status = outcome.status
    if status is None:
        return (UNAVAILABLE, "no_response")

    if status in (401, 407):
        return (RESTRICTED, "http_%d_authentication_required" % status)
    if status == 403:
        reason = "bot_challenge" if looks_like_challenge(outcome.head, outcome.content_type) \
            else "http_403_forbidden"
        return (RESTRICTED, reason)
    if status == 429:
        return (RESTRICTED, "http_429_rate_limited")
    if status in (402, 451):
        return (RESTRICTED, "http_%d_plan_or_policy_restricted" % status)
    if status == 404:
        # The host answered, so it is up; this capability is not at this path.
        return (UNAVAILABLE, "http_404_capability_not_found")
    if status in (405, 501):
        return (RESTRICTED, "http_%d_method_not_supported" % status)
    if 500 <= status < 600:
        if looks_like_challenge(outcome.head, outcome.content_type):
            return (RESTRICTED, "bot_challenge")
        return (UNAVAILABLE, "http_%d_server_error" % status)
    if 300 <= status < 400:
        return (RESTRICTED, "http_%d_redirect_not_followed" % status)
    if 200 <= status < 300:
        if looks_like_challenge(outcome.head, outcome.content_type):
            return (RESTRICTED, "bot_challenge")
        if outcome.json() is None and "json" not in (outcome.content_type or "").lower():
            return (RESTRICTED, "unexpected_payload_not_json")
        return (AVAILABLE, "ok")
    return (UNAVAILABLE, "http_%s_unclassified" % status)


def classify_rpc(outcome, expected_chain_id=None) -> tuple:
    """Classify an eth_chainId probe. Returns (state, reason, observed_chain_id)."""
    state, reason = classify_http(outcome)
    if state != AVAILABLE:
        return (state, reason, None)

    payload = outcome.json()
    if not isinstance(payload, dict):
        return (RESTRICTED, "unexpected_payload_not_jsonrpc", None)
    if "error" in payload and payload["error"] is not None:
        error = payload["error"] if isinstance(payload["error"], dict) else {}
        code = error.get("code", "unknown")
        message = redact.redact_text(str(error.get("message", "")))[:120]
        detail = "rpc_error_%s" % code
        if message:
            detail += " (%s)" % message
        return (RESTRICTED, detail, None)

    observed = net.hex_to_int(payload.get("result"))
    if observed is None:
        return (RESTRICTED, "unexpected_payload_no_result", None)
    if expected_chain_id is not None and observed != expected_chain_id:
        return (CHAIN_MISMATCH,
                "chain_id_%d_expected_%d" % (observed, expected_chain_id),
                observed)
    return (AVAILABLE, "ok", observed)


def classify_rest_coverage(payload, network_key=None) -> tuple:
    """Classify a REST provider that answered but may not index this chain.

    A provider that has never heard of Robinhood Chain is not broken and is not
    evidence about the target. It is a coverage gap, reported as chain_mismatch
    so it can never be read as a clean bill of health.
    """
    if payload is None:
        return (RESTRICTED, "unexpected_payload_not_json")
    if network_key is None:
        return (AVAILABLE, "ok")
    serialised = str(payload).lower()
    if network_key.lower() in serialised:
        return (AVAILABLE, "ok")
    return (CHAIN_MISMATCH, "provider_does_not_list_network_%s" % network_key)


def record(probe, capability, endpoint, state, reason, outcome=None,
           observed_chain_id=None, notes=None) -> dict:
    """Build a printable, credential-free health record."""
    entry = {
        "probe": probe,
        "capability": capability,
        "endpoint": redact.safe_endpoint(endpoint) if endpoint else "(not configured)",
        "host": redact.provider_label(endpoint) if endpoint else "(not configured)",
        "state": state,
        "reason": reason,
        "host_responded": bool(outcome.host_responded) if outcome else False,
        "http_status": outcome.status if outcome else None,
        "latency_ms": outcome.latency_ms if outcome else None,
        "observed_chain_id": observed_chain_id,
        "observed_at": net.now_iso(),
        "notes": list(notes or []),
    }
    if outcome is not None and outcome.retry_after:
        entry["retry_after"] = str(outcome.retry_after)[:32]
    if state == RESTRICTED:
        if str(reason).startswith(LOCAL_EGRESS_PREFIX):
            entry["notes"].append(
                "The local network or egress proxy refused this connection; the provider "
                "was never reached. Report it as a limit on this environment, never as a "
                "provider outage.")
        else:
            entry["notes"].append(
                "Host responded. This is a coverage limitation for this run, not a "
                "finding about the target.")
    if state == CHAIN_MISMATCH:
        entry["notes"].append(
            "Do not substitute another chain's data. Record the gap and continue "
            "with sources that cover the configured network.")
    return entry


def unconfigured(probe, capability, env_var, optional=True) -> dict:
    return {
        "probe": probe,
        "capability": capability,
        "endpoint": "(not configured)",
        "host": "(not configured)",
        "state": UNAVAILABLE,
        "reason": "not_configured",
        "host_responded": False,
        "http_status": None,
        "latency_ms": None,
        "observed_chain_id": None,
        "observed_at": net.now_iso(),
        "notes": ["Set %s to enable this capability." % env_var if env_var else
                  "No endpoint configured.",
                  "Optional: starter mode works without it." if optional else
                  "Required for this capability."],
    }


def summarise(records) -> dict:
    counts = {state: 0 for state in STATES}
    for entry in records:
        counts[entry["state"]] = counts.get(entry["state"], 0) + 1
    usable_state = any(
        entry["state"] == AVAILABLE and entry["capability"] == "current_onchain_state"
        for entry in records)
    return {
        "counts": counts,
        "onchain_state_readable": usable_state,
        "tier": _tier(records),
        "blocking": [] if usable_state else [
            "No RPC endpoint returned the expected chain id. Onchain claims cannot be "
            "block-pinned, so no finding above 'unknown' can be made about current state."],
    }


def _tier(records) -> str:
    enhanced = {"archive_rpc", "secondary_rpc", "alchemy", "drpc", "coingecko_pro", "defillama_pro"}
    if any(entry["probe"] in enhanced and entry["state"] == AVAILABLE for entry in records):
        return "configured_research_mode"
    return "zero_key_starter_mode"
