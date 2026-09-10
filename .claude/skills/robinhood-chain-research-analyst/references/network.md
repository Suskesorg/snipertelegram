# Robinhood Chain: what to verify, and what the layer 2 changes

## Seeded values

| | Mainnet | Testnet |
| --- | --- | --- |
| Chain id | `4663` | `46630` |
| Public RPC | `https://rpc.mainnet.chain.robinhood.com` | `https://rpc.testnet.chain.robinhood.com` |
| Explorer | `https://robinhoodchain.blockscout.com` | `https://explorer.testnet.chain.robinhood.com` |
| Gas asset | ETH | ETH |
| Architecture | EVM-compatible Arbitrum layer 2 | EVM-compatible Arbitrum layer 2 |

These shipped with the skill. They are a starting point for a first request,
not a source of truth, and endpoints change without notice.

## Verification, every session

1. **Read the chain id from the endpoint you are about to use.**

   ```bash
   python3 scripts/verify_network.py
   ```

   `eth_chainId` must return `0x1237` (4663) for mainnet or `0xb626` (46630)
   for testnet. If it returns anything else, that endpoint is not this network.
   Stop rather than continue with a footnote.

2. **Check current official documentation** for the chain id, RPC hosts, and
   explorer, and record what you checked and when in
   `network.documentation_checked`. When documentation and the RPC disagree,
   report the disagreement rather than choosing.

3. **Pin a block.** Take the head block once and read everything at that
   number. `latest` on a fast layer 2 means a different state for each call,
   and a report assembled from ten different moments cannot be reproduced.

## Never substitute another chain

The same symbol exists on many chains. The same *address* exists on many
chains too, because contracts deployed by the same deployer at the same nonce
land at the same address everywhere, and because `CREATE2` deployments are
deliberately reproduced across chains.

None of that makes another chain's data evidence here. A finding sourced from
Ethereum or Arbitrum One about "the same token" is wrong even when every
number in it is right, because it describes a different deployment with
different owners, different liquidity, and different controls.

`scripts/validate_evidence.py` refuses a bundle whose evidence carries a
different `chain_id` than the report. That check exists because this mistake is
easy to make and almost impossible to spot in finished prose.

## Never switch environments silently

Mainnet and testnet are different networks with different deployments. A
testnet address that looks identical to a mainnet one tells you nothing about
mainnet. If a request is ambiguous, ask. If you switch deliberately, say so in
the report and re-verify the chain id.

## What being an Arbitrum layer 2 changes

Most EVM habits transfer. These do not, and each has produced confidently wrong
research on other Arbitrum chains.

### `block.number` inside a contract is not the L2 block number

On Arbitrum Nitro, `block.number` read *inside the EVM* returns an estimate of
the **L1** block number. The L2 block number is what `eth_blockNumber` and
`eth_getBlockByNumber` return over RPC, and what `ArbSys.arbBlockNumber()`
returns onchain.

This matters whenever a contract implements a deadline, a vesting cliff, a
timelock delay, or a rate limit in blocks. Converting that number using L2
block times will be wrong by roughly the ratio of the two block rates. Read the
contract's own source to see which clock it uses, and prefer timestamps over
block counts when reasoning about "how long until".

Verify this behaviour holds on this chain before relying on it, by comparing
`eth_blockNumber` with an `ArbSys.arbBlockNumber()` call at the same moment.

### Precompiles worth knowing

Standard Arbitrum precompile addresses, to confirm on this chain:

| Address | Contract | Useful for |
| --- | --- | --- |
| `0x0000000000000000000000000000000000000064` | `ArbSys` | `arbBlockNumber()`, L2-to-L1 messaging |
| `0x000000000000000000000000000000000000006C` | `ArbGasInfo` | Gas price components, L1 data cost |
| `0x000000000000000000000000000000000000006D` | `ArbAggregator` | Batch poster set |
| `0x0000000000000000000000000000000000000070` | `ArbOwner` | Chain ownership surface |
| `0x00000000000000000000000000000000000000C8` | `NodeInterface` | Gas estimation, L1 confirmations |

If `eth_getCode` at these returns empty, the chain is not configured the way
you assumed, which is itself worth reporting.

### Finality is not what the RPC implies

A transaction accepted by the sequencer has a soft confirmation immediately.
It is not final until its batch is posted to the settlement layer and the
challenge or proof process completes. Between those points, the sequencer could
in principle reorder or drop it.

For research this means: a reading taken seconds after a transaction may
describe state that has not settled. Record the block hash alongside the number
so a later reader can detect a reorg. For anything time-sensitive, say which
kind of confirmation you observed.

### Determine the data availability model before drawing conclusions

Arbitrum-stack chains come in two shapes, and the difference changes who has to
be honest for the chain to work:

- **Rollup**: transaction data is posted to the settlement layer. Anyone can
  reconstruct state from it.
- **AnyTrust**: data availability is delegated to a committee, with the
  settlement layer as fallback. State reconstruction depends on that committee.

Establish which one this is from official documentation and from the on-L1
inbox configuration, and record it under `external_dependencies`. Do not assume.

### Sequencer dependency

A single sequencer is a live dependency of every conclusion about "can I sell
right now". If the sequencer is down or censoring, an onchain escape route may
exist through the delayed inbox, typically with a long forced-inclusion delay.
Whether that path exists here, and how long it takes, belongs in the
dependencies section of any report about exit risk.

### Gas has two components

Fees combine L2 execution with the cost of posting data to the settlement
layer. A transaction that looks cheap in L2 gas can be expensive because of
calldata. When modelling exit costs at the sizes in `research.exit_sizes_usd`,
do not use an L1 mental model, and do not ignore the data component.

## Historical state

Without an archive endpoint, historical state reads fail or return the current
value depending on the provider, and the second failure mode is far more
dangerous. If `ROBINHOOD_ARCHIVE_RPC_URL` is not set, do not attempt historical
balance or storage reads. Record `archive_state_unavailable` as a coverage
limitation and label affected findings `unavailable`.

To confirm an endpoint really serves archive data, read a storage slot at an
old block and at head and check that a value you know changed actually differs.
An endpoint that silently answers every historical query with current state
will otherwise produce a confident, entirely fictional history.
