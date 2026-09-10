"""Evidence, finding, and report validation.

These rules are the skill's spine. A model can always write a confident
sentence; what it cannot fake is a claim that survives these checks:

* an onchain claim carries the block it was read at,
* a claim about a contract carries the exact address it was read from,
* a claim above `inferred` rests on something other than an aggregator
  dashboard,
* a claim the evidence does not support is labelled `unknown` or
  `unavailable` and says why,
* and every strong claim names what would overturn it.

The checks are driven by `config.evidence`, so a user can loosen or tighten
them, and the validator reports which setting produced each error so the
tradeoff is visible rather than hidden.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import crypto, jsonschema_min

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"

ONCHAIN_CLASSES = {"onchain"}
CORROBORATING_CLASSES = {"explorer", "protocol_api"}
AGGREGATOR_CLASSES = {"aggregator"}
SOFT_CLASSES = {"documentation", "social", "derived"}

CONFIDENCE_ORDER = ["unavailable", "unknown", "inferred", "strongly_supported", "proven"]
STRONG = {"proven", "strongly_supported"}

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def load_schema(name: str) -> dict:
    """Load a schema, inlining {"$file": "other.schema.json"} placeholders.

    The minimal validator only resolves local #/$defs/ references, but each
    concept should still have exactly one canonical definition on disk.
    Composing at load time gives both.
    """
    path = SCHEMA_DIR / name
    if not path.exists():
        raise FileNotFoundError("schema not found: %s" % path)
    return _inline_files(json.loads(path.read_text(encoding="utf-8")), set())


def _inline_files(node, seen):
    if isinstance(node, dict):
        if set(node) == {"$file"}:
            target = node["$file"]
            if target in seen:
                raise ValueError("schema file reference loop at %s" % target)
            loaded = json.loads((SCHEMA_DIR / target).read_text(encoding="utf-8"))
            loaded.pop("$schema", None)
            loaded.pop("$id", None)
            return _inline_files(loaded, seen | {target})
        return {key: _inline_files(value, seen) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_files(item, seen) for item in node]
    return node


def validate_bundle(bundle: dict, config: dict) -> dict:
    """Validate a report bundle. Returns {'errors': [...], 'warnings': [...]}.

    Errors mean the bundle asserts something it has not earned. Warnings mean
    the bundle is publishable but thinner than the configuration asked for.
    """
    errors = list(jsonschema_min.validate(bundle, load_schema("report.schema.json")))
    warnings = []
    rules = (config or {}).get("evidence", {})
    network = (config or {}).get("network", {})

    records = [item for item in bundle.get("evidence", []) if isinstance(item, dict)]
    # Lookup map for citations, but per-record checks run over the list: a
    # duplicate id must not let the second record hide the first one's problems.
    evidence = {item.get("id"): item for item in records}
    _check_ids(bundle, errors)
    _check_network(bundle, records, network, errors)
    _check_evidence_records(records, rules, errors, warnings)
    _check_findings(bundle, evidence, rules, errors, warnings)
    _check_coverage(bundle, errors, warnings)
    return {"errors": errors, "warnings": warnings}


def _check_ids(bundle, errors):
    seen = set()
    for item in bundle.get("evidence", []):
        identifier = item.get("id") if isinstance(item, dict) else None
        if identifier in seen:
            errors.append("evidence: duplicate id %r" % identifier)
        seen.add(identifier)
    seen = set()
    for item in bundle.get("findings", []):
        identifier = item.get("id") if isinstance(item, dict) else None
        if identifier in seen:
            errors.append("findings: duplicate id %r" % identifier)
        seen.add(identifier)


def _check_network(bundle, records, network_config, errors):
    network = bundle.get("network", {})
    chain_id = network.get("chain_id")
    environment = network.get("environment")

    expected = network_config.get("expected_chain_id")
    if expected is not None and chain_id is not None and chain_id != expected:
        errors.append(
            "network.chain_id %s does not match config network.expected_chain_id %s. "
            "Never report a different network than the one requested."
            % (chain_id, expected))
    configured_environment = network_config.get("environment")
    if configured_environment and environment and environment != configured_environment:
        errors.append(
            "network.environment %r differs from the configured %r. Switching between "
            "mainnet and testnet must be an explicit, stated decision."
            % (environment, configured_environment))
    if network.get("chain_id_verified") is not True:
        errors.append(
            "network.chain_id_verified must be true: read eth_chainId from the RPC in "
            "use and record it before any onchain claim.")

    for item in records:
        identifier = item.get("id", "(unnamed evidence)")
        item_chain = item.get("chain_id")
        if item_chain is not None and chain_id is not None and item_chain != chain_id:
            errors.append(
                "%s: evidence chain_id %s does not match the report's chain %s. "
                "Same-symbol or same-address tokens on other chains are not evidence here."
                % (identifier, item_chain, chain_id))
        item_environment = item.get("network")
        if item_environment and environment and item_environment != environment:
            errors.append("%s: evidence is from %s while the report is about %s"
                          % (identifier, item_environment, environment))


def _check_evidence_records(records, rules, errors, warnings):
    require_block = rules.get("require_block_pin", True)
    require_address = rules.get("require_exact_address_binding", True)
    preserve_raw = rules.get("preserve_raw_evidence", True)

    for position, item in enumerate(records):
        identifier = item.get("id") or "evidence[%d]" % position
        kind = item.get("class")
        observed_at = item.get("observed_at", "")
        if not _ISO.match(str(observed_at)):
            errors.append("%s: observed_at must be an ISO 8601 UTC timestamp" % identifier)

        if kind in ONCHAIN_CLASSES or kind in CORROBORATING_CLASSES:
            block = item.get("block") or {}
            if require_block and not isinstance(block.get("number"), int):
                errors.append(
                    "%s: %s evidence needs block.number (evidence.require_block_pin is on). "
                    "State reads without a block are not reproducible."
                    % (identifier, kind))
            if isinstance(block.get("number"), int) and not block.get("hash"):
                warnings.append("%s: block.hash missing; a reorg would make this unverifiable"
                                % identifier)

        if kind in AGGREGATOR_CLASSES or kind in SOFT_CLASSES:
            if item.get("freshness") == "block_pinned" and not (item.get("block") or {}).get("number"):
                errors.append("%s: freshness says block_pinned but no block is recorded" % identifier)
            if item.get("freshness") == "real_time":
                errors.append(
                    "%s: cached REST data must not be labelled real_time. Use 'cached' or "
                    "'unknown_cache' and record the observation timestamp." % identifier)
            if kind in AGGREGATOR_CLASSES and not item.get("cache_note"):
                warnings.append("%s: no cache_note. Say what the provider documents about "
                                "staleness, or record that it is undocumented." % identifier)

        subject = item.get("subject") or {}
        address = subject.get("address")
        if require_address and kind in (ONCHAIN_CLASSES | CORROBORATING_CLASSES):
            if not address:
                errors.append("%s: subject.address is required (evidence.require_exact_address_binding)"
                              % identifier)
            elif not crypto.is_hex_address(address):
                errors.append("%s: subject.address %r is not a 20-byte hex address"
                              % (identifier, address))
            elif not crypto.is_checksum_address(address):
                warnings.append("%s: subject.address is not EIP-55 checksummed (expected %s)"
                                % (identifier, crypto.to_checksum_address(address)))

        if preserve_raw and kind in ONCHAIN_CLASSES:
            if not item.get("raw") and not item.get("raw_ref"):
                errors.append("%s: raw or raw_ref is required (evidence.preserve_raw_evidence). "
                              "Keep the response so the reading can be re-checked." % identifier)

        source = str(item.get("source_host", ""))
        if "://" in source or "?" in source:
            errors.append("%s: source_host must be a bare host, never a full URL with a query "
                          "string that could carry a credential" % identifier)


def _check_findings(bundle, evidence, rules, errors, warnings):
    allow_dashboard = rules.get("allow_dashboard_only_claims", False)
    min_proven = rules.get("min_sources_for_proven", 1)
    min_strong = rules.get("min_sources_for_strongly_supported", 2)

    for finding in bundle.get("findings", []):
        if not isinstance(finding, dict):
            continue
        identifier = finding.get("id", "(unnamed finding)")
        confidence = finding.get("confidence")
        cited = [evidence[e] for e in finding.get("evidence_ids", []) if e in evidence]
        missing = [e for e in finding.get("evidence_ids", []) if e not in evidence]
        for absent in missing:
            errors.append("%s: cites %s, which is not in the evidence list" % (identifier, absent))

        if confidence in STRONG or confidence == "inferred":
            if not cited:
                errors.append("%s: confidence %r requires at least one evidence record"
                              % (identifier, confidence))
            if not finding.get("falsifier"):
                errors.append("%s: needs a falsifier - the observation that would overturn it"
                              % identifier)
        if confidence == "inferred" and not finding.get("reasoning"):
            errors.append("%s: an inferred finding must show the reasoning from evidence to claim"
                          % identifier)
        if confidence in ("unknown", "unavailable") and not finding.get("why_unknown"):
            errors.append("%s: %r findings must say what was attempted and what blocked it"
                          % (identifier, confidence))
        if confidence == "unavailable" and not finding.get("coverage_limitation_ids"):
            errors.append("%s: 'unavailable' must point at the coverage limitation that caused it, "
                          "so a provider limit is never mistaken for a property of the target"
                          % identifier)

        hard = [item for item in cited if item.get("class") in (ONCHAIN_CLASSES | CORROBORATING_CLASSES)]
        onchain = [item for item in cited if item.get("class") in ONCHAIN_CLASSES]
        if confidence == "proven":
            if len(onchain) < max(1, min_proven):
                errors.append("%s: 'proven' needs at least %d onchain evidence record(s); it has %d"
                              % (identifier, max(1, min_proven), len(onchain)))
        if confidence == "strongly_supported" and len(cited) < min_strong:
            warnings.append("%s: 'strongly_supported' is configured to want %d sources; it has %d"
                            % (identifier, min_strong, len(cited)))
        if confidence in STRONG and not hard and not allow_dashboard:
            errors.append(
                "%s: rests only on aggregator or narrative sources. Aggregate dashboards are not "
                "proof of contract-level behaviour (evidence.allow_dashboard_only_claims is off). "
                "Bind it to an exact contract read or lower the confidence." % identifier)

        subject = finding.get("subject_address")
        if subject and rules.get("require_exact_address_binding", True):
            addresses = [(item.get("subject") or {}).get("address") for item in cited]
            addresses = [a for a in addresses if a]
            if addresses and not any(crypto.same_address(subject, a) for a in addresses):
                errors.append(
                    "%s: subject_address %s appears in none of its evidence records. A finding must "
                    "be bound to the exact address it was read from." % (identifier, subject))

        if finding.get("focus_area") is None:
            warnings.append("%s: no focus_area, so it will not map onto the configured focus list"
                            % identifier)


def _check_coverage(bundle, errors, warnings):
    health = bundle.get("provider_health", [])
    degraded = [entry for entry in health
                if isinstance(entry, dict)
                and entry.get("state") in ("reachable_but_restricted", "chain_mismatch", "unavailable")]
    limitations = bundle.get("coverage_limitations", [])
    if degraded and not limitations:
        errors.append(
            "provider_health records %d degraded provider(s) but coverage_limitations is empty. "
            "Rate limits, pruning, bot protection and missing indexing must be disclosed as "
            "limits on the run, not left implicit." % len(degraded))
    for entry in limitations:
        if isinstance(entry, dict) and not entry.get("effect"):
            warnings.append("%s: say what this limitation prevented, not just that it happened"
                            % entry.get("id", "(coverage limitation)"))
    if bundle.get("findings") and not bundle.get("disclaimers"):
        warnings.append("disclaimers: state plainly that this is research, not investment advice, "
                        "a safety score, or an exploit audit")


def summarise(bundle: dict) -> dict:
    counts = {level: 0 for level in CONFIDENCE_ORDER}
    for finding in bundle.get("findings", []):
        if isinstance(finding, dict):
            level = finding.get("confidence")
            counts[level] = counts.get(level, 0) + 1
    return {
        "findings": len(bundle.get("findings", [])),
        "evidence": len(bundle.get("evidence", [])),
        "by_confidence": counts,
        "coverage_limitations": len(bundle.get("coverage_limitations", [])),
    }
