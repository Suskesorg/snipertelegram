# Investigation playbooks

One playbook per focus area. Read the one you are working on. Each gives the
question, the steps, the traps that produce confidently wrong answers, the
highest confidence the method can reach, and a rough request cost against the
30-request first-pass budget.

Exact call shapes are in `references/rpc-recipes.md`. Every selector, topic,
and storage slot referenced here is printed by `python3 scripts/slots.py`,
computed from its preimage rather than copied from memory.

## Contents

1. [identity_and_source](#identity_and_source)
2. [contract_controls](#contract_controls)
3. [proxy_and_upgrade_risk](#proxy_and_upgrade_risk)
4. [liquidity_custody](#liquidity_custody)
5. [sellability_and_exit_depth](#sellability_and_exit_depth)
6. [holder_concentration](#holder_concentration)
7. [fees_and_treasury](#fees_and_treasury)
8. [rwa_rights_and_redemption](#rwa_rights_and_redemption)
9. [external_dependencies](#external_dependencies)
10. [launch_and_distribution](#launch_and_distribution)
11. [market_context](#market_context)
12. [narrative_and_sentiment](#narrative_and_sentiment)

---

## identity_and_source

**Question.** Is this the exact thing the user asked about, and what is it?

**Steps.**

1. `eth_getCode(target, block)` at the pinned block. Empty means an externally
   owned account, or a contract not yet deployed at that block. Both are
   findings, and they are different findings.
2. Hash the runtime code. That hash is the contract's fingerprint and the thing
   to compare against what the explorer claims is deployed.
3. Token probes, if it might be one: `name()`, `symbol()`, `decimals()`,
   `totalSupply()`. Some tokens return `bytes32` rather than `string` from the
   first two; `crypto.decode_string` handles both shapes.
4. Explorer lookup for verification status, source, ABI, compiler, and proxy
   detection.
5. **Compare the explorer's reported deployed bytecode with `eth_getCode`.**
   This is the step that converts "the explorer says it is verified" into
   "the verified source corresponds to the code that is actually running".
6. Creation transaction and deployer address, from the explorer.

**Traps.**

- *Verified is not safe.* Verification means the source compiles to the
  deployed bytecode. A verified contract can mint infinitely and block anyone.
- *Verified source may describe the proxy, not the implementation.* Read the
  implementation's source too; that is where the behaviour lives.
- *Same address, different chain.* Reproducible deployment addresses are
  deliberate. Confirm the chain id on the endpoint you read from.
- *Same symbol, different token.* This is why `pons_default_selection` defaults
  to `require_address`.

**Reachable confidence.** `proven` for existence, code hash, and token
metadata. `strongly_supported` for verification, once the runtime comparison
agrees.

**Cost.** 4 to 7 requests.

---

## contract_controls

**Question.** Who can change what, and what can they do to a holder?

**Steps.**

1. Enumerate the ABI for privileged entry points. What matters is not their
   names but their effects: mint, burn from another address, pause, blocklist
   or freeze, set fees, set an oracle, sweep tokens, upgrade, transfer
   ownership.
2. Read ownership: `owner()`, `pendingOwner()`, `admin()`. A zero owner means
   renounced *for that mechanism only*, which is not the same as uncontrolled.
3. Read roles, if AccessControl-style: `DEFAULT_ADMIN_ROLE()`, then the role
   ids the source defines. Role ids are `keccak256` of a string, so compute
   them from source rather than guessing:
   `python3 scripts/slots.py --slot "MINTER_ROLE"`.
4. `hasRole(role, account)` for each candidate; `getRoleMember` and
   `getRoleMemberCount` if the enumerable extension is present.
5. Scan `RoleGranted`, `RoleRevoked`, `OwnershipTransferred` logs in bounded
   ranges to see how control has moved.
6. **Classify every controller address.** This is the step most reports skip,
   and it is where the actual risk lives:
   - `eth_getCode` empty means a single key. One person, one compromise.
   - A Safe-style multisig answers `getOwners()` and `getThreshold()`. Read
     both. A 1-of-3 multisig is one key wearing a costume.
   - A timelock answers `getMinDelay()`. Read the delay and read who holds its
     proposer and executor roles. A timelock whose admin can shorten its own
     delay is a speed bump.
7. Read the transfer path in source. Does `transfer` carry `whenNotPaused`, a
   blocklist check, a fee, a maximum, a cooldown, an allowlist?

**Traps.**

- *Renounced ownership theatre.* `owner()` returns zero while a role, a
  separate admin contract, or the proxy admin retains full power.
- *A multisig is only as good as its threshold and its signer set.* Both are
  onchain. Read them.
- *A pause you cannot see in the ABI.* Restrictions are often inside a hook or
  a base contract. Read the implementation source, not just the selector list.
- *An unverified implementation.* You can still read storage slots and observe
  behaviour, but control claims drop to `inferred` at best. Say so.

**Reachable confidence.** `proven` for role holders and current state.
`strongly_supported` for "these are all the privileged functions", which
depends on reading source and can never be exhaustive without an audit.

**Cost.** 8 to 15 requests.

---

## proxy_and_upgrade_risk

**Question.** Can the code behind this address be replaced, and by whom?

**Steps.**

1. Read the standard slots with `eth_getStorageAt` at the pinned block. All are
   computed from preimages by `scripts/slots.py`:
   - EIP-1967 implementation, admin, beacon
   - EIP-1822 (UUPS) `PROXIABLE`
   - Legacy ZeppelinOS implementation and admin
2. A non-zero beacon slot means the implementation is read from a beacon.
   Read `implementation()` on the beacon, and find out who owns the beacon,
   because that owner upgrades every proxy pointing at it at once.
3. If a `ProxyAdmin` contract sits in the admin slot, read its `owner()`. The
   admin contract is rarely the real answer.
4. For diamonds (EIP-2535), `facetAddresses()` and `facets()` enumerate the
   implementation surface, which can change per function.
5. Scan `Upgraded(address)`, `AdminChanged(address,address)`, and
   `BeaconUpgraded(address)` logs. Upgrade cadence is informative: a contract
   upgraded three times last month is a live codebase, not a settled one.
6. Follow the chain of control to the end: implementation, admin, admin's
   owner, that owner's threshold or timelock delay. Report the whole chain.

**Traps.**

- *Explorer proxy detection is a heuristic.* Confirm by reading storage.
- *A transparent proxy's `implementation()` reverts for non-admin callers.*
  Read the slot instead of concluding it is not a proxy.
- *Every behavioural finding is implementation-scoped.* Say so explicitly: the
  report describes the implementation at the pinned block.
- *Immutable is a claim until proven.* Zero in every slot, plus no upgrade
  path in source, is the proof.

**Reachable confidence.** `proven` for slot contents and the control chain.

**Cost.** 5 to 10 requests.

---

## liquidity_custody

**Question.** Where is the liquidity, and who can remove it?

**Steps.**

1. Discover venues with GeckoTerminal or CoinGecko. Discovery only.
2. Bind each pool to an exact address, then read the pool contract at the
   pinned block: `token0()`, `token1()`, `getReserves()` for constant-product
   pools; `slot0()` and `liquidity()` for concentrated-liquidity pools.
3. Confirm the pool actually contains the target token. A pool named after a
   symbol may hold a different contract with the same symbol.
4. Read the LP token: `totalSupply()`, then `balanceOf()` for the largest
   holders from the explorer's holder list.
5. Classify the LP holders. The important cases:
   - The deployer or a related address: the position can leave at will.
   - A burn address (`0x0…0`, `0x…dEaD`): permanently locked, verifiable.
   - A locker contract: read *that contract* for the unlock time and the
     beneficiary. A lock that a beneficiary can extend, shorten, or migrate is
     not a lock.
   - Dispersed holders: the healthy case, and rare early on.
6. For concentrated liquidity, note that positions are NFTs with ranges. A
   large notional in a narrow range far from the current price is not depth
   where it matters. If you cannot enumerate positions within budget, say the
   depth analysis is range-blind rather than reporting a total.

**Traps.**

- *"Liquidity locked" screenshots.* Verify the locker contract onchain or do
  not repeat the claim.
- *Depth in the wrong direction.* A pool can be deep in the quote asset and
  thin in the token, or the reverse. Sell-side depth is what matters for exit.
- *Multiple pools with different quote assets.* Aggregate carefully and say
  which venue each number came from.

**Reachable confidence.** `proven` for reserves and LP balances at the block.
`inferred` for intent, always.

**Cost.** 6 to 12 requests per venue.

---

## sellability_and_exit_depth

**Question.** Could an ordinary holder actually sell, at the sizes in
`research.exit_sizes_usd`?

This is the question retail readers care about most and the one most often
answered with a market-cap number that has nothing to do with it.

**Steps.**

1. For each configured size, convert to token units at the pinned-block price
   derived from pool reserves, not from a dashboard.
2. Compute expected output and price impact from the pool's own math. For a
   constant-product pool with a 0.3 percent fee:

   ```
   out = (in * 997 * reserve_out) / (reserve_in * 1000 + in * 997)
   ```

   Confirm the fee tier before using it; it varies by venue and by pool.
3. **Simulate the real path, not just the quote.** A router quote answers "what
   would the math give" and ignores transfer taxes, blocklists, cooldowns, and
   pause states. Use `eth_call` at the pinned block, with `from` set to an
   address that actually holds the token, along the full path a seller would
   take. A simulation that reverts is a finding.
4. Check the restriction surface found in `contract_controls` against the sell
   path: can the caller be blocked, can transfers be paused, is there a maximum
   transaction size, a cooldown, or a sell-side fee that differs from the buy
   side?
5. Report per size: expected proceeds, price impact, whether the simulation
   succeeded, and what would block it. If a size exceeds available depth, say
   the depth was not found rather than extrapolating.

**Traps.**

- *Quoting from `getAmountsOut` alone.* It is the most common false negative
  for a token that cannot actually be sold.
- *Simulating from an address with no balance.* The revert then tells you
  nothing about sellability.
- *Ignoring gas and the layer 2 data component* at small sizes, where they can
  be most of the cost.
- *Treating market cap or 24-hour volume as exit depth.* They are unrelated.
  Volume can be wash traded; depth cannot be, at a pinned block.

**Reachable confidence.** `proven` for reserves and for a simulation result at
a block. `inferred` for what a real seller would experience, since price moves
and other sellers exist.

**Cost.** 4 to 8 requests per size.

---

## holder_concentration

**Question.** Who holds this, and how concentrated is it?

**Steps.**

1. Get the holder list from the explorer. This is usually the first thing to
   hit a rate limit; if it does, record the coverage limitation and label the
   finding `unavailable` rather than reasoning from a partial page.
2. Compute top-1, top-10, and top-50 shares of supply.
3. **Annotate every large holder before interpreting anything.** Unannotated
   concentration numbers are close to meaningless. Classify each as: the pool
   itself, a bridge, a staking or vesting contract, a custodian, an exchange
   wallet, the treasury, the deployer, or unknown.
4. Subtract the structural holders and recompute. Concentration among
   *discretionary* holders is the number that speaks to risk.
5. Check whether large holders are contracts or keys (`eth_getCode`), and
   whether they cluster: funded by the same address, deployed by the same
   deployer, moving in the same blocks.

**Traps.**

- *Custody is not insider concentration.* For a tokenized real-world asset,
  one address holding most of the supply may be exactly the design.
- *Exchange wallets aggregate many users.* Counting one as a whale is wrong.
- *Contract holders are not holders.* A pool holding 40 percent of supply is
  liquidity, not an owner.
- *A partial holder list is not a distribution.* Never extrapolate from page
  one.

**Reachable confidence.** `proven` for balances read onchain.
`strongly_supported` for a distribution, if the list is complete.
`inferred` for clustering and attribution, always.

**Cost.** 3 to 10 requests, plus one per holder classified.

---

## fees_and_treasury

**Question.** Where does the money go?

**Steps.**

1. Read fee parameters from the contracts: rates, recipients, splits, and who
   can change each one.
2. Follow the recipient address. Is it a splitter, a treasury multisig, a
   single key, or a burn?
3. Read treasury balances at the pinned block: native balance plus
   `balanceOf()` for each material token. Do not take a dashboard's total.
4. Establish whether treasury movement requires a timelock or a threshold, from
   `contract_controls`.
5. Use DeFiLlama for revenue and fee context, clearly marked as protocol-level
   context that does not establish contract behaviour.
6. For collateralised or reserve-backed assets, read the reserve holdings and
   compare with claimed backing. If backing is offchain, that is an issuer
   dependency, not an onchain fact, and belongs in
   `rwa_rights_and_redemption`.

**Traps.**

- *Fee rate without changeability.* A 0.1 percent fee that one key can raise to
  99 percent is a 99 percent fee with extra steps.
- *Treasury totals from dashboards.* Read the balances.
- *Confusing revenue with profit, or fees with revenue.* Say which is which
  and where the number came from.

**Reachable confidence.** `proven` for balances and parameters at the block.

**Cost.** 5 to 12 requests.

---

## rwa_rights_and_redemption

**Question.** For a tokenized real-world asset, what does the holder actually
have?

See `references/rwa-and-dependencies.md` for the full treatment. The short
version: separate what the chain enforces from what a company promises. The
chain can enforce transfer and balance. It cannot enforce redemption, custody,
or a claim on an underlying asset.

**Cost.** 6 to 15 requests, plus documentation reading.

---

## external_dependencies

**Question.** What outside this contract could change every conclusion above?

Work through this list, and record each as present, absent, or unchecked:

| Dependency | What to establish |
| --- | --- |
| Oracle | Which contract, who can update it, staleness and heartbeat, deviation bounds, what happens on a stale read |
| Bridge | Canonical or third party, who can mint the wrapped asset, what backs it |
| Sequencer | Single operator, is there a delayed-inbox escape, how long is forced inclusion |
| Data availability | Rollup or committee-based (see `references/network.md`) |
| Issuer | Who they are, what they have committed to, what happens if they stop |
| Custodian | Who holds the underlying, what attestation exists, how often |
| Upstream protocol | Morpho markets, Lighter venues, or any protocol whose state this depends on. Corroborate against exact contracts or venue timestamps |
| Off-chain API | Anything a redemption, a KYC gate, or a price depends on |
| Legal or regulatory | Transfer restrictions, jurisdiction limits, eligibility gates |

For each present dependency: what breaks if it fails, and can a holder do
anything about it.

**Trap.** Dependencies are where "the contract is fine" reports go wrong. The
contract usually is fine. The oracle, the bridge, or the issuer is the risk.

**Reachable confidence.** `proven` for oracle addresses and configuration read
onchain. `inferred` or `unknown` for most offchain dependencies.

**Cost.** 5 to 15 requests.

---

## launch_and_distribution

Runs when `research.include_historical_launch_analysis` is `always`, or when
`when_triggered` and the target is young, concentrated, or the user asked.

**Needs an archive endpoint.** Without one, say so and stop; do not
reconstruct history from current state.

**Steps.** Find the deployment block from the creation transaction. Scan
`Transfer` logs forward from it in bounded ranges. Identify the first
recipients, the initial liquidity event, and any allocation to the deployer or
related addresses. Compare initial allocations with current balances to see
what moved.

**Trap.** A clean launch does not make a token safe now, and a messy one does
not make it a scam. This is context for the control findings, not a verdict.

**Cost.** 10 or more requests. Budget for it deliberately.

---

## market_context

Price, volume, market cap, TVL, and comparisons, from GeckoTerminal, CoinGecko,
and DeFiLlama. Always labelled `cached` or `unknown_cache` with an observation
timestamp, never `real_time`, and never used to support a contract-level claim.

Useful for: is there any market at all, is volume plausible relative to depth,
how does this compare to its category.

**Trap.** Volume can be manufactured. Reserves at a pinned block cannot.

**Cost.** 2 to 5 requests.

---

## narrative_and_sentiment

With `X_BEARER_TOKEN`, sample within `research.sentiment_window_hours`, capped
at `research.social_sample_limit`, and record the query so it can be re-drawn.

Without a token, whatever web search surfaces is **search-visible narrative**,
shaped by ranking and recency. Label it exactly that way. Do not quantify it,
do not call it sentiment, and do not let it support a technical finding.

Useful for: what claims are being made, so they can be checked onchain. That
is the whole value. A claim found here becomes a question for a playbook above.

**Trap.** Coordinated promotion is indistinguishable from organic enthusiasm
from the inside. Treat volume of discussion as evidence of promotion effort,
not of quality.

**Cost.** 1 to 5 requests.
