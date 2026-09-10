"""The shipped artifacts have to be internally consistent, and the command line
helpers have to behave the way the documentation says they do."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rhclib import config as cfglib  # noqa: E402
from rhclib import evidence as evidencelib  # noqa: E402
from rhclib import jsonschema_min  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable] + [str(a) for a in args],
                          capture_output=True, text=True, cwd=str(ROOT))


class TestSchemas(unittest.TestCase):
    def test_all_schemas_parse(self):
        for path in sorted((ROOT / "schemas").glob("*.json")):
            json.loads(path.read_text(encoding="utf-8"))

    def test_schemas_use_only_supported_keywords(self):
        for name in ("config.schema.json", "evidence-record.schema.json",
                     "finding.schema.json", "report.schema.json"):
            schema = evidencelib.load_schema(name)
            self.assertEqual(jsonschema_min.unsupported_keywords(schema), [], name)

    def test_report_schema_inlines_its_file_references(self):
        schema = evidencelib.load_schema("report.schema.json")
        self.assertIn("properties", schema["$defs"]["evidenceRecord"])
        self.assertIn("properties", schema["$defs"]["finding"])
        self.assertNotIn("$file", json.dumps(schema))

    def test_focus_areas_agree_across_schema_and_defaults(self):
        config_schema = evidencelib.load_schema("config.schema.json")
        allowed = set(config_schema["properties"]["research"]["properties"]["focus"]["items"]["enum"])
        finding_schema = evidencelib.load_schema("finding.schema.json")
        self.assertEqual(set(finding_schema["properties"]["focus_area"]["enum"]), allowed)
        self.assertTrue(set(cfglib.DEFAULTS["research"]["focus"]).issubset(allowed))

    def test_defaults_match_the_shipped_example(self):
        settings, _ = cfglib.load_config(str(ROOT / "config.example.yaml"))
        for section in ("analyst", "network", "research", "evidence", "providers"):
            for key, value in cfglib.DEFAULTS[section].items():
                self.assertIn(key, settings[section], "%s.%s" % (section, key))
        self.assertEqual(settings["research"]["focus"], cfglib.DEFAULTS["research"]["focus"])
        self.assertEqual(cfglib.validate_config(settings), [])


class TestCommandLine(unittest.TestCase):
    def test_validate_config_accepts_the_example(self):
        result = run("scripts/validate_config.py", "--config", "config.example.yaml")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Configuration is valid", result.stdout)

    def test_validate_config_json_mode(self):
        result = run("scripts/validate_config.py", "--config", "config.example.yaml", "--json")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertTrue(all("configured" in row for row in payload["environment"]))

    def test_offline_health_check_reports_each_state(self):
        result = run("scripts/check_providers.py", "--config", "config.example.yaml",
                     "--offline", "--fixture", "fixtures/provider_health_mixed.json", "--json")
        payload = json.loads(result.stdout)
        states = {entry["state"] for entry in payload["providers"]}
        self.assertIn("available", states)
        self.assertIn("reachable_but_restricted", states)
        self.assertIn("chain_mismatch", states)
        self.assertIn("unavailable", states)
        self.assertEqual(payload["mode"], "offline_fixture")

    def test_wrong_chain_fixture_fails_the_run(self):
        result = run("scripts/check_providers.py", "--config", "config.example.yaml",
                     "--offline", "--fixture", "fixtures/provider_health_wrong_chain.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLOCKING", result.stdout)

    def test_starter_mode_fixture_passes(self):
        result = run("scripts/check_providers.py", "--config", "config.example.yaml",
                     "--offline", "--fixture", "fixtures/provider_health_starter_ok.json")
        self.assertEqual(result.returncode, 0)

    def test_evidence_validator_exit_codes(self):
        good = run("scripts/validate_evidence.py", "fixtures/report_valid.json",
                   "--config", "config.example.yaml")
        self.assertEqual(good.returncode, 0, good.stdout)
        bad = run("scripts/validate_evidence.py", "fixtures/report_invalid.json",
                  "--config", "config.example.yaml")
        self.assertEqual(bad.returncode, 1)

    def test_strict_mode_fails_on_warnings(self):
        result = run("scripts/validate_evidence.py", "fixtures/report_valid.json",
                     "--config", "config.example.yaml", "--strict")
        self.assertEqual(result.returncode, 1)

    def test_slots_command_computes_known_values(self):
        result = run("scripts/slots.py", "--selector", "transfer(address,uint256)")
        self.assertEqual(result.stdout.strip(), "0xa9059cbb")

    def test_redact_stream_filters_stdin(self):
        secret = "sk_live_9f2b7c41aa5e4d0e8b31"
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "redact_stream.py")],
            input="key %s in a log line" % secret, capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "SOME_PROVIDER_API_KEY": secret})
        self.assertNotIn(secret, process.stdout)
        self.assertIn("SOME_PROVIDER_API_KEY", process.stdout)


class TestSkillPackage(unittest.TestCase):
    def test_skill_md_frontmatter_is_well_formed(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        closing = text.index("\n---\n", 3)
        frontmatter = text[4:closing]
        fields = {}
        for line in frontmatter.splitlines():
            if ":" in line and not line.startswith(" "):
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
        self.assertIn("name", fields)
        self.assertIn("description", fields)
        self.assertEqual(fields["name"], "robinhood-chain-research-analyst")
        self.assertLessEqual(len(fields["description"]), 1024)
        self.assertNotIn("<", fields["description"])
        self.assertNotIn(">", fields["description"])

    def test_referenced_files_exist(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for folder in ("references", "schemas", "scripts", "fixtures", "assets"):
            for path in (ROOT / folder).iterdir():
                if path.name.startswith("__") or path.suffix == ".pyc":
                    continue
        import re
        for match in re.findall(r"`((?:references|schemas|scripts|fixtures|assets)/[\w./-]+)`", text):
            self.assertTrue((ROOT / match).exists(), "SKILL.md points at missing %s" % match)

    def test_no_credentials_committed(self):
        suspicious = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix in (".pyc",):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for marker in ("sk_live_", "Bearer ey", "-----BEGIN"):
                if marker in text and "test_" not in path.name:
                    suspicious.append("%s contains %r" % (path.name, marker))
        self.assertEqual(suspicious, [])


if __name__ == "__main__":
    unittest.main()
