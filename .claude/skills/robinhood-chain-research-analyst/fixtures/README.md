# Fixtures

Everything in this directory is **synthetic**. Nothing here was read from any
chain, and no address, balance, pool, or holder in these files corresponds to a
real deployment. They exist so the validation helpers can be exercised, and
their failure modes demonstrated, with no network access and no live
investigation.

## How to tell a fixture address from a real one

Every address in these files is derived from a label, so anyone can confirm it
was invented rather than observed:

```
address = checksum("0x" + keccak256("synthetic:<label>").hex()[-40:])
```

Reproduce them with the skill's own helper:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts")
from rhclib import crypto
label = "synthetic:example-token"
print(crypto.to_checksum_address("0x" + crypto.keccak256(label).hex()[-40:]))
PY
```

| Label                              | Address                                      |
| ---------------------------------- | -------------------------------------------- |
| `synthetic:example-token`          | `0x217339e01AdaBa70e8875791ff848AbF44365671` |
| `synthetic:example-implementation` | `0x887eF1CBb15180e7d0d869EabEaa09a668CF2b7c` |
| `synthetic:example-proxy-admin`    | `0x8EAa5fB5bFD7814a40A2e555235A04d1ccc0926C` |
| `synthetic:example-timelock`       | `0x647c54E51753f68B250557455Bbea33A7426C0C8` |
| `synthetic:example-pool`           | `0x6E4E4C1ad3c21E71C8C873EB36c59de58C443817` |
| `synthetic:example-treasury`       | `0xE20fe3e186fEb2855b8150e945B84605E85be01b` |
| `synthetic:example-deployer`       | `0xAA520E2313F4BafeC37DB38C95153A5cd55b912b` |

## Files

| File | What it is for |
| --- | --- |
| `provider_health_starter_ok.json` | Zero-key starter mode where everything answers. |
| `provider_health_mixed.json` | One of each state: a rate limit, a bot challenge, a wrong chain, a dead host. |
| `provider_health_wrong_chain.json` | The RPC answers cleanly about a different chain. The run must stop. |
| `report_valid.json` | A report bundle that satisfies every evidence rule. |
| `report_invalid.json` | A report bundle that breaks each rule once, for testing the validator's messages. |

`report_invalid.json` is intentionally wrong. Do not use it as a template.
