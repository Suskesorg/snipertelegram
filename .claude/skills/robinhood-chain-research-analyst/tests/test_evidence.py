"""The evidence rules are what stop a confident sentence from passing as a
finding. These tests check that each rule fires, and that turning a rule off in
configuration actually changes the outcome."""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rhclib import config as cfglib  # noqa: E402
from rhclib import evidence as evidencelib  # noqa: E402


def load_settings():
    settings, _ = cfglib.load_config(str(ROOT / "config.example.yaml"))
    return settings


def load_bundle(name):
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


class TestValidBundle(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()
        self.bundle = load_bundle("report_valid.json")

    def test_it_passes(self):
        result = evidencelib.validate_bundle(self.bundle, self.settings)
        self.assertEqual(result["errors"], [])

    def test_summary_counts_confidence_levels(self):
        summary = evidencelib.summarise(self.bundle)
        self.assertEqual(summary["findings"], 7)
        self.assertEqual(summary["by_confidence"]["proven"], 2)
        self.assertEqual(summary["by_confidence"]["unavailable"], 1)


class TestInvalidBundle(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()
        self.errors = evidencelib.validate_bundle(
            load_bundle("report_invalid.json"), self.settings)["errors"]

    def assertReported(self, needle):
        self.assertTrue(any(needle in item for item in self.errors),
                        "no error mentioned %r; got:\n%s" % (needle, "\n".join(self.errors)))

    def test_unverified_chain_id_is_refused(self):
        self.assertReported("chain_id_verified")

    def test_evidence_from_another_chain_is_refused(self):
        self.assertReported("does not match the report's chain")

    def test_missing_block_pin_is_refused(self):
        self.assertReported("require_block_pin")

    def test_missing_raw_evidence_is_refused(self):
        self.assertReported("preserve_raw_evidence")

    def test_dashboard_only_proof_is_refused(self):
        self.assertReported("Aggregate dashboards are not proof")

    def test_unbound_address_is_refused(self):
        self.assertReported("appears in none of its evidence records")

    def test_missing_falsifier_is_refused(self):
        self.assertReported("needs a falsifier")

    def test_inferred_without_reasoning_is_refused(self):
        self.assertReported("must show the reasoning")

    def test_unknown_without_explanation_is_refused(self):
        self.assertReported("what was attempted and what blocked it")

    def test_unavailable_must_name_its_coverage_limitation(self):
        self.assertReported("must point at the coverage limitation")

    def test_cached_data_labelled_real_time_is_refused(self):
        self.assertReported("must not be labelled real_time")

    def test_credential_bearing_source_is_refused(self):
        self.assertReported("source_host must be a bare host")

    def test_dangling_citation_is_refused(self):
        self.assertReported("not in the evidence list")

    def test_undisclosed_coverage_gap_is_refused(self):
        self.assertReported("coverage_limitations is empty")

    def test_duplicate_ids_are_refused(self):
        self.assertReported("duplicate id")


class TestRulesFollowConfiguration(unittest.TestCase):
    """Loosening a rule has to actually loosen it, or the setting is a lie."""

    def setUp(self):
        self.settings = load_settings()
        self.bundle = load_bundle("report_valid.json")

    def errors_for(self, bundle, **evidence_overrides):
        settings = cfglib.deep_merge(self.settings, {"evidence": evidence_overrides})
        return evidencelib.validate_bundle(bundle, settings)["errors"]

    def test_block_pin_rule_can_be_relaxed(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["evidence"][0].pop("block")
        self.assertTrue(any("require_block_pin" in e for e in self.errors_for(bundle)))
        self.assertEqual([e for e in self.errors_for(bundle, require_block_pin=False)
                          if "require_block_pin" in e], [])

    def test_dashboard_rule_can_be_relaxed(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["findings"][0]["evidence_ids"] = ["EV-007"]
        bundle["findings"][0]["confidence"] = "strongly_supported"
        self.assertTrue(any("Aggregate dashboards" in e for e in self.errors_for(bundle)))
        self.assertEqual([e for e in self.errors_for(bundle, allow_dashboard_only_claims=True)
                          if "Aggregate dashboards" in e], [])

    def test_raising_the_proven_bar_tightens_the_check(self):
        bundle = copy.deepcopy(self.bundle)
        self.assertEqual(self.errors_for(bundle), [])
        errors = self.errors_for(bundle, min_sources_for_proven=3)
        self.assertTrue(any("'proven' needs at least 3" in e for e in errors), errors)

    def test_network_mismatch_against_configuration_is_refused(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["network"]["environment"] = "testnet"
        bundle["network"]["chain_id"] = 46630
        errors = evidencelib.validate_bundle(bundle, self.settings)["errors"]
        self.assertTrue(any("expected_chain_id" in e for e in errors), errors)
        self.assertTrue(any("mainnet and testnet" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
