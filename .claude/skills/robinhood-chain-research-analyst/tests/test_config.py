"""The configuration must mean the same thing with or without PyYAML, and it
must catch the mistakes a non-developer is most likely to make."""

import builtins
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rhclib import config as cfglib  # noqa: E402


class TestParserAgreement(unittest.TestCase):
    def test_mini_parser_matches_pyyaml_on_the_shipped_example(self):
        text = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
        mini = cfglib._mini_yaml(text)
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed, nothing to compare against")
        self.assertEqual(mini, yaml.safe_load(text))

    def test_loads_without_pyyaml(self):
        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("simulated missing PyYAML")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = blocked
        try:
            settings, _ = cfglib.load_config(str(ROOT / "config.example.yaml"))
        finally:
            builtins.__import__ = real_import
        self.assertEqual(settings["network"]["expected_chain_id"], 4663)
        self.assertEqual(settings["research"]["exit_sizes_usd"], [1000, 10000, 100000])

    def test_malformed_input_says_which_line(self):
        with self.assertRaises(cfglib.ConfigError) as caught:
            cfglib._mini_yaml("analyst:\n  style concise\n")
        self.assertIn("line 2", str(caught.exception))


class TestValidation(unittest.TestCase):
    def load(self, **overrides):
        settings, _ = cfglib.load_config(str(ROOT / "config.example.yaml"))
        return cfglib.deep_merge(settings, overrides)

    def test_shipped_example_is_valid(self):
        self.assertEqual(cfglib.validate_config(self.load()), [])

    def test_unknown_key_is_rejected_with_a_suggestion(self):
        errors = cfglib.validate_config(self.load(research={"exit_sizes_used": [1]}))
        self.assertTrue(errors)
        self.assertIn("exit_sizes_used", errors[0])
        self.assertIn("exit_sizes_usd", errors[0])

    def test_environment_and_chain_id_must_agree(self):
        errors = cfglib.validate_config(self.load(network={"environment": "testnet"}))
        self.assertTrue(any("46630" in e for e in errors), errors)

    def test_testnet_pairing_is_accepted(self):
        errors = cfglib.validate_config(
            self.load(network={"environment": "testnet", "expected_chain_id": 46630}))
        self.assertEqual(errors, [])

    def test_contradictory_evidence_settings_are_caught(self):
        errors = cfglib.validate_config(self.load(evidence={"allow_dashboard_only_claims": True}))
        self.assertTrue(any("contradict" in e for e in errors), errors)

    def test_unsorted_exit_sizes_are_caught(self):
        errors = cfglib.validate_config(self.load(research={"exit_sizes_usd": [100000, 1000]}))
        self.assertTrue(any("ascending" in e for e in errors), errors)

    def test_bad_enum_value_is_rejected(self):
        errors = cfglib.validate_config(self.load(analyst={"risk_posture": "yolo"}))
        self.assertTrue(any("risk_posture" in e for e in errors), errors)


class TestEnvironmentResolution(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)
        self.settings, _ = cfglib.load_config(str(ROOT / "config.example.yaml"))

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_default_slot_names(self):
        self.assertEqual(cfglib.env_name(self.settings, "primary_rpc"), "ROBINHOOD_RPC_URL")

    def test_alias_by_slot(self):
        settings = cfglib.deep_merge(self.settings,
                                     {"providers": {"env_aliases": {"primary_rpc": "MY_L2_RPC"}}})
        self.assertEqual(cfglib.env_name(settings, "primary_rpc"), "MY_L2_RPC")

    def test_alias_by_default_variable_name(self):
        settings = cfglib.deep_merge(
            self.settings, {"providers": {"env_aliases": {"COINGECKO_API_KEY": "CG_PRO_KEY"}}})
        self.assertEqual(cfglib.env_name(settings, "coingecko_key"), "CG_PRO_KEY")

    def test_public_fallback_when_nothing_is_set(self):
        os.environ.pop("ROBINHOOD_RPC_URL", None)
        url, source = cfglib.endpoint(self.settings, "primary_rpc")
        self.assertEqual(url, "https://rpc.mainnet.chain.robinhood.com")
        self.assertIn("public_rpc_url", source)

    def test_fallback_follows_the_selected_environment(self):
        settings = cfglib.deep_merge(
            self.settings, {"network": {"environment": "testnet", "expected_chain_id": 46630}})
        os.environ.pop("ROBINHOOD_RPC_URL", None)
        url, _ = cfglib.endpoint(settings, "primary_rpc")
        self.assertEqual(url, "https://rpc.testnet.chain.robinhood.com")

    def test_env_report_never_contains_a_value(self):
        os.environ["ROBINHOOD_RPC_URL"] = "https://secret-host.example/v2/abcdef0123456789abcdef"
        rows = cfglib.env_report(self.settings)
        self.assertNotIn("abcdef0123456789abcdef", str(rows))
        primary = [r for r in rows if r["slot"] == "primary_rpc"][0]
        self.assertTrue(primary["configured"])
        self.assertIn("url", primary["value_shape"])


if __name__ == "__main__":
    unittest.main()
