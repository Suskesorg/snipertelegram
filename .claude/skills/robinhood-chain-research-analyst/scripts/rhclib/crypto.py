"""Keccak-256, EIP-55 checksums, function selectors, event topics, proxy slots.

Pure standard library, no dependencies.

Why this exists: the skill's evidence rules require binding every claim to an
exact address, and proxy/upgrade checks require reading specific storage slots.
Both are places where a memorised constant is a silent-failure risk. Computing
selectors and slots from their preimages makes the constants checkable instead
of trusted, and `tests/test_crypto.py` pins the implementation to published
Keccak test vectors.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Keccak-f[1600]
# --------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1


def _round_constants() -> list:
    """Generate the 24 Keccak round constants from the spec LFSR."""
    constants = []
    lfsr = 1
    for _ in range(24):
        value = 0
        for j in range(7):
            if lfsr & 1:
                value ^= 1 << ((1 << j) - 1)
            # LFSR over x^8 + x^6 + x^5 + x^4 + 1
            if lfsr & 0x80:
                lfsr = ((lfsr << 1) ^ 0x71) & 0xFF
            else:
                lfsr = (lfsr << 1) & 0xFF
        constants.append(value)
    return constants


def _rho_offsets() -> list:
    """Generate the rho rotation offsets by walking the spec's (x, y) path."""
    offsets = [[0] * 5 for _ in range(5)]
    x, y = 1, 0
    for t in range(24):
        offsets[x][y] = ((t + 1) * (t + 2) // 2) % 64
        x, y = y, (2 * x + 3 * y) % 5
    return offsets


_RC = _round_constants()
_R = _rho_offsets()


def _rol(value: int, shift: int) -> int:
    shift %= 64
    return ((value << shift) | (value >> (64 - shift))) & _MASK64 if shift else value


def _keccak_f(state: list) -> list:
    for rnd in range(24):
        # theta
        c = [state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x][y] ^= d[x]
        # rho and pi
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(state[x][y], _R[x][y])
        # chi
        for x in range(5):
            for y in range(5):
                state[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y] & _MASK64)
        # iota
        state[0][0] ^= _RC[rnd]
    return state


def keccak256(data) -> bytes:
    """Keccak-256 (the pre-standard variant Ethereum uses, domain byte 0x01)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("keccak256 expects bytes or str")
    rate = 136  # 1088 bits
    message = bytearray(data)
    # pad10*1
    message.append(0x01)
    while len(message) % rate != 0:
        message.append(0x00)
    message[-1] ^= 0x80

    state = [[0] * 5 for _ in range(5)]
    for offset in range(0, len(message), rate):
        block = message[offset:offset + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8:(i + 1) * 8], "little")
            state[i % 5][i // 5] ^= lane
        state = _keccak_f(state)

    out = bytearray()
    while len(out) < 32:
        for i in range(rate // 8):
            if len(out) >= 32:
                break
            out += state[i % 5][i // 5].to_bytes(8, "little")
    return bytes(out[:32])


def keccak256_hex(data) -> str:
    return "0x" + keccak256(data).hex()


# --------------------------------------------------------------------------
# Addresses
# --------------------------------------------------------------------------

def is_hex_address(value) -> bool:
    if not isinstance(value, str) or not value.startswith("0x") or len(value) != 42:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in value[2:])


def to_checksum_address(address: str) -> str:
    """EIP-55 checksummed address. Raises ValueError on anything else."""
    if not is_hex_address(address):
        raise ValueError("not a 20-byte hex address: %r" % (address,))
    lowered = address[2:].lower()
    digest = keccak256(lowered.encode("ascii")).hex()
    out = ["0x"]
    for index, ch in enumerate(lowered):
        if ch in "0123456789":
            out.append(ch)
        else:
            out.append(ch.upper() if int(digest[index], 16) >= 8 else ch)
    return "".join(out)


def is_checksum_address(address: str) -> bool:
    try:
        return to_checksum_address(address) == address
    except ValueError:
        return False


def same_address(a: str, b: str) -> bool:
    """Case-insensitive equality for two hex addresses. Never fuzzy-match."""
    if not (is_hex_address(a) and is_hex_address(b)):
        return False
    return a.lower() == b.lower()


# --------------------------------------------------------------------------
# ABI helpers
# --------------------------------------------------------------------------

def selector(signature: str) -> str:
    """4-byte function selector, e.g. selector('transfer(address,uint256)')."""
    return "0x" + keccak256(signature).hex()[:8]


def event_topic(signature: str) -> str:
    """32-byte topic0 for an event signature."""
    return keccak256_hex(signature)


def encode_call(signature: str, *args: str) -> str:
    """Minimal calldata encoder for static 32-byte args (address/uint/bool/bytes32).

    Deliberately limited: dynamic types are not supported, because silently
    mis-encoding a dynamic argument would produce a plausible-looking wrong
    answer. Build dynamic calldata with a real ABI library and record it in the
    evidence bundle instead.
    """
    data = selector(signature)
    for arg in args:
        data += encode_word(arg)
    return data


def encode_word(value) -> str:
    if isinstance(value, bool):
        return "%064x" % (1 if value else 0)
    if isinstance(value, int):
        if value < 0:
            raise ValueError("negative integers are not supported")
        return "%064x" % value
    if isinstance(value, str):
        if is_hex_address(value):
            return "%064x" % int(value, 16)
        if value.startswith("0x"):
            raw = value[2:]
            if len(raw) > 64:
                raise ValueError("value wider than 32 bytes: %s" % value)
            return raw.rjust(64, "0").lower()
    raise TypeError("unsupported static argument: %r" % (value,))


def decode_address(word: str) -> str:
    """Take a 32-byte return word and read the trailing address out of it."""
    raw = word[2:] if word.startswith("0x") else word
    if len(raw) < 40:
        raise ValueError("return word too short for an address")
    return to_checksum_address("0x" + raw[-40:])


def decode_uint(word: str) -> int:
    raw = word[2:] if word.startswith("0x") else word
    if raw == "":
        raise ValueError("empty return data")
    return int(raw, 16)


def decode_string(return_data: str) -> str:
    """Decode an ABI-encoded string return, falling back to bytes32 strings.

    Some tokens return bytes32 from name()/symbol() instead of string. Both
    shapes appear on real chains, so both are handled, and the caller is told
    which shape was seen by the length of the payload.
    """
    raw = return_data[2:] if return_data.startswith("0x") else return_data
    if raw == "":
        raise ValueError("empty return data")
    data = bytes.fromhex(raw)
    if len(data) == 32:
        return data.rstrip(b"\x00").decode("utf-8", errors="replace")
    if len(data) >= 64:
        offset = int.from_bytes(data[0:32], "big")
        if offset + 32 <= len(data):
            length = int.from_bytes(data[offset:offset + 32], "big")
            start = offset + 32
            return data[start:start + length].decode("utf-8", errors="replace")
    return data.rstrip(b"\x00").decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Proxy storage slots, computed from their preimages
# --------------------------------------------------------------------------

def slot_minus_one(preimage: str) -> str:
    """keccak256(preimage) - 1, the EIP-1967 construction."""
    value = int.from_bytes(keccak256(preimage), "big") - 1
    return "0x" + ("%064x" % (value & ((1 << 256) - 1)))


def slot_direct(preimage: str) -> str:
    return keccak256_hex(preimage)


#: Storage slots worth reading on any contract that might be a proxy.
#: Each entry records how the slot is derived so a reader can recompute it.
PROXY_SLOTS = {
    "eip1967.implementation": ("minus_one", "eip1967.proxy.implementation"),
    "eip1967.admin": ("minus_one", "eip1967.proxy.admin"),
    "eip1967.beacon": ("minus_one", "eip1967.proxy.beacon"),
    "eip1822.proxiable": ("direct", "PROXIABLE"),
    "zeppelinos.implementation": ("direct", "org.zeppelinos.proxy.implementation"),
    "zeppelinos.admin": ("direct", "org.zeppelinos.proxy.admin"),
}


def proxy_slots() -> dict:
    """Map slot name to {slot, derivation, preimage}."""
    out = {}
    for name, (kind, preimage) in PROXY_SLOTS.items():
        slot = slot_minus_one(preimage) if kind == "minus_one" else slot_direct(preimage)
        out[name] = {
            "slot": slot,
            "derivation": "keccak256(preimage) - 1" if kind == "minus_one" else "keccak256(preimage)",
            "preimage": preimage,
        }
    return out


#: Read-only calls that are cheap, standard, and worth trying on any target.
#: Signature -> what a successful answer tells you.
PROBE_CALLS = {
    "name()": "token or contract name",
    "symbol()": "token symbol",
    "decimals()": "token decimals",
    "totalSupply()": "total supply in base units",
    "owner()": "Ownable owner",
    "pendingOwner()": "Ownable2Step pending owner",
    "admin()": "proxy admin (transparent proxy, admin-only call)",
    "implementation()": "proxy implementation (admin-only on transparent proxies)",
    "paused()": "pause state",
    "getRoleAdmin(bytes32)": "AccessControl role wiring",
    "DEFAULT_ADMIN_ROLE()": "AccessControl default admin role id",
    "MINTER_ROLE()": "AccessControl minter role id",
    "PAUSER_ROLE()": "AccessControl pauser role id",
    "BLACKLISTER_ROLE()": "freeze or blocklist role id",
    "isBlacklisted(address)": "per-address transfer restriction",
    "isFrozen(address)": "per-address freeze",
    "maxFlashLoan(address)": "flash-mint capability",
}

#: Event topics worth scanning for in bounded log queries.
CONTROL_EVENTS = [
    "Upgraded(address)",
    "AdminChanged(address,address)",
    "BeaconUpgraded(address)",
    "OwnershipTransferred(address,address)",
    "OwnershipTransferStarted(address,address)",
    "RoleGranted(bytes32,address,address)",
    "RoleRevoked(bytes32,address,address)",
    "Paused(address)",
    "Unpaused(address)",
    "Transfer(address,address,uint256)",
    "Approval(address,address,uint256)",
]
