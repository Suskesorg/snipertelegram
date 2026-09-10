"""Each provider state must be reachable, and they must not collapse into each
other. A rate limit read as 'offline' is how a coverage gap turns into a false
statement about a target."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rhclib import health, net  # noqa: E402


def outcome(status=None, body=None, body_text="", content_type=None, error_kind=None,
            retry_after=None):
    head = json.dumps(body) if body is not None else body_text
    if content_type is None:
        content_type = "application/json" if body is not None else "text/html"
    return net.HttpOutcome(status=status, head=head, content_type=content_type,
                           error_kind=error_kind, retry_after=retry_after, latency_ms=10)


class TestTransportClassification(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(health.classify_http(outcome(200, {"ok": True}))[0], health.AVAILABLE)

    def test_authentication_and_authorisation_are_restricted_not_down(self):
        for status in (401, 403, 407):
            state, reason = health.classify_http(outcome(status, body_text="no", content_type="text/plain"))
            self.assertEqual(state, health.RESTRICTED, status)
            self.assertIn(str(status), reason)

    def test_rate_limit_is_restricted_and_keeps_retry_after(self):
        result = outcome(429, body_text="slow down", content_type="text/plain", retry_after="30")
        state, reason = health.classify_http(result)
        self.assertEqual(state, health.RESTRICTED)
        self.assertIn("rate_limited", reason)
        record = health.record("p", "c", "https://host.example/api", state, reason, outcome=result)
        self.assertEqual(record["retry_after"], "30")
        self.assertTrue(record["host_responded"])

    def test_bot_protection_is_not_offline(self):
        challenge = outcome(403, body_text="<html><title>Just a moment...</title>cf-chl</html>",
                            content_type="text/html")
        state, reason = health.classify_http(challenge)
        self.assertEqual(state, health.RESTRICTED)
        self.assertEqual(reason, "bot_challenge")

    def test_challenge_served_with_a_2xx_is_still_a_challenge(self):
        challenge = outcome(200, body_text="<html>Checking your browser</html>", content_type="text/html")
        self.assertEqual(health.classify_http(challenge), (health.RESTRICTED, "bot_challenge"))

    def test_html_where_json_was_asked_for_is_restricted(self):
        state, reason = health.classify_http(outcome(200, body_text="<html>hello</html>",
                                                     content_type="text/html"))
        self.assertEqual(state, health.RESTRICTED)

    def test_network_failures_are_unavailable_and_keep_their_cause(self):
        for kind in ("timeout", "dns_failure", "connect_error", "tls_error", "proxy_error"):
            state, reason = health.classify_http(outcome(error_kind=kind))
            self.assertEqual(state, health.UNAVAILABLE, kind)
            self.assertEqual(reason, kind)

    def test_server_error_is_unavailable(self):
        state, reason = health.classify_http(outcome(503, body_text="oops", content_type="text/plain"))
        self.assertEqual(state, health.UNAVAILABLE)
        self.assertIn("503", reason)

    def test_every_state_is_reachable(self):
        produced = set()
        produced.add(health.classify_http(outcome(200, {"ok": 1}))[0])
        produced.add(health.classify_http(outcome(429, body_text="x", content_type="text/plain"))[0])
        produced.add(health.classify_http(outcome(error_kind="dns_failure"))[0])
        produced.add(health.classify_rpc(outcome(200, {"result": "0xa4b1"}), 4663)[0])
        self.assertEqual(produced, set(health.STATES))


class TestRpcClassification(unittest.TestCase):
    def test_expected_chain_is_available(self):
        state, reason, observed = health.classify_rpc(outcome(200, {"result": "0x1237"}), 4663)
        self.assertEqual((state, reason, observed), (health.AVAILABLE, "ok", 4663))

    def test_wrong_chain_is_its_own_state(self):
        state, reason, observed = health.classify_rpc(outcome(200, {"result": "0xa4b1"}), 4663)
        self.assertEqual(state, health.CHAIN_MISMATCH)
        self.assertEqual(observed, 42161)
        self.assertIn("expected_4663", reason)

    def test_testnet_chain_id(self):
        state, _, observed = health.classify_rpc(outcome(200, {"result": "0xb626"}), 46630)
        self.assertEqual((state, observed), (health.AVAILABLE, 46630))

    def test_rpc_level_error_is_restricted(self):
        payload = {"error": {"code": -32601, "message": "method not found"}}
        state, reason, _ = health.classify_rpc(outcome(200, payload), 4663)
        self.assertEqual(state, health.RESTRICTED)
        self.assertIn("-32601", reason)

    def test_json_that_is_not_jsonrpc_is_restricted(self):
        state, reason, _ = health.classify_rpc(outcome(200, {"nonsense": 1}), 4663)
        self.assertEqual(state, health.RESTRICTED)
        self.assertIn("no_result", reason)


class TestCoverage(unittest.TestCase):
    def test_provider_without_this_chain_is_a_mismatch_not_a_failure(self):
        state, reason = health.classify_rest_coverage([{"name": "Ethereum"}], "Robinhood Chain")
        self.assertEqual(state, health.CHAIN_MISMATCH)
        self.assertIn("does_not_list", reason)

    def test_provider_listing_the_chain_is_available(self):
        state, _ = health.classify_rest_coverage([{"name": "Robinhood Chain"}], "Robinhood Chain")
        self.assertEqual(state, health.AVAILABLE)


class TestRecordsAndSummary(unittest.TestCase):
    def test_records_never_contain_the_endpoint_credential(self):
        url = "https://rpc.example.com/v2/abcdef0123456789abcdef0123"
        entry = health.record("primary_rpc", "current_onchain_state", url,
                              health.AVAILABLE, "ok", outcome=outcome(200, {"result": "0x1237"}))
        self.assertNotIn("abcdef0123456789abcdef0123", json.dumps(entry))

    def test_restricted_records_explain_themselves(self):
        entry = health.record("blockscout", "contract_discovery_and_source",
                              "https://explorer.example.com", health.RESTRICTED,
                              "http_429_rate_limited", outcome=outcome(429, body_text="x"))
        self.assertTrue(any("not a finding about the target" in note for note in entry["notes"]))

    def test_summary_blocks_when_no_rpc_is_usable(self):
        entry = health.record("primary_rpc", "current_onchain_state", "https://h.example",
                              health.CHAIN_MISMATCH, "chain_id_1_expected_4663")
        summary = health.summarise([entry])
        self.assertFalse(summary["onchain_state_readable"])
        self.assertTrue(summary["blocking"])

    def test_tier_detection(self):
        starter = [health.record("primary_rpc", "current_onchain_state", "https://h.example",
                                 health.AVAILABLE, "ok")]
        self.assertEqual(health.summarise(starter)["tier"], "zero_key_starter_mode")
        enhanced = starter + [health.record("archive_rpc", "historical_state", "https://h.example",
                                            health.AVAILABLE, "ok")]
        self.assertEqual(health.summarise(enhanced)["tier"], "configured_research_mode")


class TestBudget(unittest.TestCase):
    def test_request_budget_stops_the_run(self):
        budget = net.RequestBudget(max_requests=2)
        budget.spend_request()
        budget.spend_request()
        with self.assertRaises(net.BudgetExceeded):
            budget.spend_request()

    def test_failure_cap_per_check(self):
        budget = net.RequestBudget(max_failures_per_check=2)
        self.assertFalse(budget.record_failure("holder_list"))
        self.assertTrue(budget.record_failure("holder_list"))
        self.assertIn("holder_list", budget.snapshot()["checks_abandoned"])


if __name__ == "__main__":
    unittest.main()


class TestLocalEgress(unittest.TestCase):
    """A proxy that answers and refuses is our network, not their outage."""

    def test_proxy_denial_is_restricted_not_unavailable(self):
        state, reason = health.classify_http(outcome(error_kind="proxy_denied_403"))
        self.assertEqual(state, health.RESTRICTED)
        self.assertEqual(reason, "proxy_denied_403")

    def test_the_note_blames_the_environment_not_the_provider(self):
        entry = health.record("coingecko_public", "market_context", "https://api.example.com",
                              health.RESTRICTED, "proxy_denied_403")
        self.assertTrue(any("never reached" in note for note in entry["notes"]), entry["notes"])
        self.assertFalse(any("Host responded" in note for note in entry["notes"]))

    def test_a_dead_proxy_is_still_unavailable(self):
        self.assertEqual(health.classify_http(outcome(error_kind="proxy_error")),
                         (health.UNAVAILABLE, "proxy_error"))

    def test_error_kind_extraction(self):
        self.assertEqual(net._url_error_kind(OSError("Tunnel connection failed: 403 Forbidden")),
                         "proxy_denied_403")
        self.assertEqual(net._url_error_kind(OSError("Connection refused")), "connect_error")
