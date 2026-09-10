"""A credential must not survive into anything a person or a file can read."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rhclib import redact  # noqa: E402

SECRET = "sk_live_9f2b7c41aa5e4d0e8b31"
KEYED_URL = "https://rpc-provider.example.com/v2/" + SECRET


class RedactionCase(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)
        os.environ["TEST_PROVIDER_API_KEY"] = SECRET
        os.environ["TEST_PROVIDER_RPC_URL"] = KEYED_URL

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)


class TestEndpointRendering(RedactionCase):
    def test_key_bearing_path_is_cut(self):
        rendered = redact.safe_endpoint(KEYED_URL)
        self.assertNotIn(SECRET, rendered)
        self.assertIn("rpc-provider.example.com", rendered)
        self.assertIn("/v2/", rendered + "/")

    def test_query_string_is_dropped_whole(self):
        rendered = redact.safe_endpoint("https://api.example.com/v3/coins?x_cg_pro_api_key=" + SECRET)
        self.assertNotIn(SECRET, rendered)
        self.assertNotIn("x_cg_pro_api_key=" + SECRET, rendered)

    def test_userinfo_credentials_are_stripped(self):
        rendered = redact.safe_endpoint("https://user:%s@rpc.example.com/v1" % SECRET)
        self.assertNotIn(SECRET, rendered)

    def test_public_paths_stay_readable(self):
        # A redacted endpoint is useless if it cannot tell two providers apart.
        rendered = redact.safe_endpoint("https://robinhoodchain.blockscout.com/api/v2/stats")
        self.assertEqual(rendered, "https://robinhoodchain.blockscout.com/api/v2/stats")

    def test_addresses_are_not_mistaken_for_credentials(self):
        url = "https://explorer.example.com/api/v2/addresses/0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
        self.assertIn("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", redact.safe_endpoint(url))

    def test_unparseable_input_is_not_echoed(self):
        self.assertEqual(redact.safe_endpoint("not a url at all"), "[REDACTED]")


class TestTextAndObjects(RedactionCase):
    def test_env_value_is_replaced_by_its_variable_name(self):
        out = redact.redact_text("connecting with key %s now" % SECRET)
        self.assertNotIn(SECRET, out)
        self.assertIn("TEST_PROVIDER_API_KEY", out)

    def test_command_line_is_safe_to_log(self):
        command = 'curl -H "Authorization: Bearer %s" %s' % (SECRET, KEYED_URL)
        out = redact.redact_text(command)
        self.assertNotIn(SECRET, out)

    def test_nested_structures_are_redacted(self):
        payload = {"providers": [{"api_key": SECRET, "url": KEYED_URL}], "note": "uses " + SECRET}
        out = redact.redact_obj(payload)
        self.assertNotIn(SECRET, str(out))

    def test_short_values_are_left_alone(self):
        os.environ["TEST_SHORT_TOKEN"] = "true"
        self.assertIn("true", redact.redact_text("the flag is true"))

    def test_assert_no_secrets_raises_on_a_leak(self):
        with self.assertRaises(AssertionError):
            redact.assert_no_secrets("report mentioning %s" % SECRET)
        redact.assert_no_secrets("a clean report")

    def test_provider_label_is_host_only(self):
        self.assertEqual(redact.provider_label(KEYED_URL), "rpc-provider.example.com")


if __name__ == "__main__":
    unittest.main()
