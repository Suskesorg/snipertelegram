"""Pin the hashing helpers to published vectors.

If any of these fail, every computed selector, topic, storage slot, and
checksum in the skill is suspect, so they run first.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rhclib import crypto  # noqa: E402


class TestKeccak(unittest.TestCase):
    def test_published_vectors(self):
        self.assertEqual(
            crypto.keccak256_hex(""),
            "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
        self.assertEqual(
            crypto.keccak256_hex("abc"),
            "0x4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45")

    def test_multi_block_input(self):
        # Longer than the 136-byte rate, so the sponge absorbs more than once.
        digest = crypto.keccak256("a" * 500)
        self.assertEqual(len(digest), 32)
        self.assertNotEqual(digest, crypto.keccak256("a" * 499))

    def test_known_event_topics(self):
        self.assertEqual(
            crypto.event_topic("Transfer(address,address,uint256)"),
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef")

    def test_known_selectors(self):
        self.assertEqual(crypto.selector("transfer(address,uint256)"), "0xa9059cbb")
        self.assertEqual(crypto.selector("approve(address,uint256)"), "0x095ea7b3")
        self.assertEqual(crypto.selector("balanceOf(address)"), "0x70a08231")
        self.assertEqual(crypto.selector("totalSupply()"), "0x18160ddd")
        self.assertEqual(crypto.selector("owner()"), "0x8da5cb5b")


class TestChecksum(unittest.TestCase):
    #: The address examples published with EIP-55.
    VECTORS = [
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
        "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
        "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
    ]

    def test_checksums_round_trip(self):
        for address in self.VECTORS:
            self.assertEqual(crypto.to_checksum_address(address.lower()), address)
            self.assertTrue(crypto.is_checksum_address(address))

    def test_rejects_non_addresses(self):
        for bad in ("0xNOTANADDRESS", "5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed", "0x1234", ""):
            self.assertFalse(crypto.is_hex_address(bad))
            with self.assertRaises(ValueError):
                crypto.to_checksum_address(bad)

    def test_same_address_is_case_insensitive_but_not_fuzzy(self):
        a = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
        self.assertTrue(crypto.same_address(a, a.lower()))
        self.assertFalse(crypto.same_address(a, "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAee"))
        self.assertFalse(crypto.same_address(a, "not an address"))


class TestProxySlots(unittest.TestCase):
    def test_eip1967_slots_match_the_standard(self):
        slots = crypto.proxy_slots()
        self.assertEqual(slots["eip1967.implementation"]["slot"],
                         "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc")
        self.assertEqual(slots["eip1967.admin"]["slot"],
                         "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103")
        self.assertEqual(slots["eip1967.beacon"]["slot"],
                         "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50")

    def test_every_slot_records_how_it_was_derived(self):
        for name, entry in crypto.proxy_slots().items():
            self.assertIn("preimage", entry, name)
            self.assertTrue(entry["slot"].startswith("0x"), name)
            self.assertEqual(len(entry["slot"]), 66, name)


class TestDecoding(unittest.TestCase):
    def test_decode_address_from_return_word(self):
        word = "0x" + "00" * 12 + "5aaeb6053f3e94c9b9a09f33669435e7ef1beaed"
        self.assertEqual(crypto.decode_address(word),
                         "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed")

    def test_decode_uint(self):
        self.assertEqual(crypto.decode_uint("0x" + "0" * 62 + "12"), 18)

    def test_decode_string_handles_both_shapes(self):
        packed = ("0x" + "%064x" % 32 + "%064x" % 5
                  + "48656c6c6f".ljust(64, "0"))
        self.assertEqual(crypto.decode_string(packed), "Hello")
        bytes32 = "0x" + "48656c6c6f".ljust(64, "0")
        self.assertEqual(crypto.decode_string(bytes32), "Hello")

    def test_encode_call_rejects_dynamic_arguments(self):
        with self.assertRaises(TypeError):
            crypto.encode_call("foo(string)", ["not static"])


if __name__ == "__main__":
    unittest.main()
