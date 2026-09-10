# RPC recipes

Concrete request shapes. Two conventions throughout:

- `$RPC` is an environment variable. Use the variable, never a pasted URL, so a
  credential in the endpoint never reaches your scrollback, your notes, or the
  report. Pipe anything uncertain through `scripts/redact_stream.py`.
- `$BLOCK` is the pinned block as a hex quantity, for example `0x496e79`. Read
  everything at it. `latest` is a moving target and makes the report
  irreproducible.

```bash
export RPC="${ROBINHOOD_RPC_URL:-https://rpc.mainnet.chain.robinhood.com}"
BLOCK=$(python3 - <<'PY'
print(hex(4812345))
PY
)
```

A small helper for the examples below:

```bash
rpc() {  # rpc METHOD JSON_PARAMS
  curl -s -X POST "$RPC" -H 'content-type: application/json' \
    --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}" \
    | python3 "$SKILL/scripts/redact_stream.py"
}
```

## Identity

```bash
rpc eth_chainId '[]'                                  # must match expected_chain_id
rpc eth_getBlockByNumber '["latest", false]'          # pin number, hash, timestamp
rpc eth_getCode "[\"$ADDR\", \"$BLOCK\"]"             # "0x" means no contract
rpc eth_getBalance "[\"$ADDR\", \"$BLOCK\"]"
```

Fingerprint the runtime so the explorer's claim can be checked against it:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts")
from rhclib import crypto
runtime = "0x60806040..."        # exactly what eth_getCode returned
print(crypto.keccak256_hex(bytes.fromhex(runtime[2:])))
PY
```

## Static reads with `eth_call`

Every no-argument getter is `{"to": ADDR, "data": SELECTOR}` at `$BLOCK`:

```bash
rpc eth_call "[{\"to\":\"$ADDR\",\"data\":\"0x06fdde03\"}, \"$BLOCK\"]"   # name()
rpc eth_call "[{\"to\":\"$ADDR\",\"data\":\"0x95d89b41\"}, \"$BLOCK\"]"   # symbol()
rpc eth_call "[{\"to\":\"$ADDR\",\"data\":\"0x313ce567\"}, \"$BLOCK\"]"   # decimals()
rpc eth_call "[{\"to\":\"$ADDR\",\"data\":\"0x18160ddd\"}, \"$BLOCK\"]"   # totalSupply()
rpc eth_call "[{\"to\":\"$ADDR\",\"data\":\"0x8da5cb5b\"}, \"$BLOCK\"]"   # owner()
rpc eth_call "[{\"to\":\"$ADDR\",\"data\":\"0x5c975abb\"}, \"$BLOCK\"]"   # paused()
```

`python3 scripts/slots.py` prints the full table. For a selector not in it:

```bash
python3 scripts/slots.py --selector "hasRole(bytes32,address)"
```

One-argument calls take a 32-byte word after the selector:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts")
from rhclib import crypto
print(crypto.encode_call("balanceOf(address)", "0x217339e01AdaBa70e8875791ff848AbF44365671"))
PY
```

`encode_call` handles static arguments only. It refuses dynamic types rather
than mis-encoding them, because a silently wrong argument returns a
plausible-looking wrong answer.

### Reading the results

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts")
from rhclib import crypto
print(crypto.decode_uint("0x0000...0012"))        # 18
print(crypto.decode_address("0x0000...5671"))     # checksummed
print(crypto.decode_string("0x0000...")) 	  # handles string and bytes32 shapes
PY
```

An `eth_call` that reverts is a result, not an error to retry. Record it: a
`transfer` that reverts from a real holder is one of the strongest sellability
findings available.

## Proxy slots

```bash
python3 scripts/slots.py                          # every slot, with its preimage
IMPL=0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc
rpc eth_getStorageAt "[\"$ADDR\", \"$IMPL\", \"$BLOCK\"]"
```

A slot holding `0x0…0` is empty. A non-zero slot holds a left-padded address;
take the last 40 hex characters and checksum it:

```bash
python3 scripts/slots.py --checksum 0x887ef1cbb15180e7d0d869eabeaa09a668cf2b7c
```

Read all six slots. A contract can be an EIP-1967 proxy, a UUPS proxy, a beacon
proxy, or a legacy ZeppelinOS proxy, and the wrong assumption reads an empty
slot and concludes "not a proxy".

## Log queries

Public endpoints cap the block range and the result count. Split the range and
page rather than asking for everything:

```bash
TOPIC=$(python3 scripts/slots.py --topic "Upgraded(address)")
rpc eth_getLogs "[{\"address\":\"$ADDR\",\"topics\":[\"$TOPIC\"],\
\"fromBlock\":\"0x4966c0\",\"toBlock\":\"0x498dc0\"}]"
```

Rules that keep this cheap and honest:

- Keep each span at or under `research.log_block_range_limit` (default 10,000).
- Always filter by `address` and by `topics[0]`. An unfiltered scan is the
  fastest way to exhaust the request budget.
- Indexed arguments appear in `topics[1..3]`, left-padded to 32 bytes. To
  filter `Transfer` by sender, put the padded address in `topics[1]`.
- A range that returns exactly the provider's maximum result count was almost
  certainly truncated. Split it and re-query; do not assume you saw everything.
- Record the exact ranges you scanned. "No upgrade events" is only true for the
  range you looked at, and the report should say which range that was.

## Simulating a sale

The point is to exercise the real path, including transfer hooks, taxes,
blocklists, and pause states, none of which a router quote sees.

```bash
rpc eth_call "[{\"from\":\"$HOLDER\",\"to\":\"$TOKEN\",\"data\":\"$TRANSFER_CALLDATA\"}, \"$BLOCK\"]"
```

- `$HOLDER` must be an address that actually holds the token at `$BLOCK`.
  Simulating from an empty address proves nothing.
- Simulate each leg a seller would perform, not only the router quote.
- A revert is a finding. Record the revert reason if one is returned; it often
  names the restriction directly.
- Some providers support state overrides on `eth_call`, which allows simulating
  from a synthetic holder. Support is provider-specific: if you use it, record
  that the result depended on an override, because it is a simulation of a
  situation that does not exist onchain.

## Historical reads

Every one of these needs an archive endpoint:

```bash
rpc eth_getBalance "[\"$ADDR\", \"0x1e8480\"]"
rpc eth_getStorageAt "[\"$ADDR\", \"$SLOT\", \"0x1e8480\"]"
```

Prove the endpoint is really archive before trusting it: read a slot you know
changed, at an old block and at head, and confirm the values differ. An
endpoint that silently answers historical queries with current state produces a
confident and entirely fictional history.

## Blockscout

```bash
BS="https://robinhoodchain.blockscout.com"
curl -s "$BS/api/v2/smart-contracts/$ADDR"           # verification, source, ABI, proxy
curl -s "$BS/api/v2/addresses/$ADDR"                 # creator, creation tx
curl -s "$BS/api/v2/tokens/$ADDR"                    # token metadata, holder count
curl -s "$BS/api/v2/tokens/$ADDR/holders"            # holder list, paginated
curl -s "$BS/api/v2/addresses/$ADDR/transactions"    # activity
```

Paths differ between Blockscout versions. A 404 means this path is not on this
instance, not that the chain is down; `scripts/check_providers.py` reports
alternative paths to try. Confirm the current API shape from the instance
itself rather than assuming.

Whatever the explorer says about proxies, verification, or balances is a lead.
Confirm anything load-bearing against RPC.

## Budget arithmetic

The 30-request first-pass budget goes roughly:

| Step | Requests |
| --- | --- |
| Chain id and head block | 2 |
| Identity and token metadata | 5 |
| Proxy slots | 6 |
| Ownership and roles | 6 |
| Pool discovery and reserves | 6 |
| One sell simulation | 3 |

That is 28, and it answers "what is this, who controls it, can I sell". Deeper
work needs a deliberate budget extension, which means stopping and asking.
