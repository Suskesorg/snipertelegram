# Evidence standards

The purpose of these rules is narrow: to make it hard to write a sentence that
sounds established when it is not. Fluency is free and correctness is not, so
the rules constrain the fluent part.

## The confidence ladder

| Label | What it asserts | Minimum evidence |
| --- | --- | --- |
| `proven` | Read directly from chain state | An `onchain` record at a pinned block, bound to the exact address |
| `strongly_supported` | Independent sources agree | Two or more sources, at least one of them onchain or explorer-class |
| `inferred` | Reasoned from evidence, not read directly | Evidence plus the reasoning written out |
| `unknown` | Not established by this run | A statement of what was attempted and what stopped it |
| `unavailable` | Could not be checked at all | A named coverage limitation |

Two rules people get wrong:

- **`unknown` is not a weaker `no`.** "No admin key was found" and "the admin
  key could not be determined" are different claims. Only the second is honest
  when the check did not complete.
- **`unavailable` is about the run, not the target.** It means a provider
  limit, a missing credential, or a pruned history stopped you. It never means
  the property is absent.

## Binding: every claim names its address

A claim about a contract carries the exact address it was read from, in EIP-55
checksummed form. Symbols, names, and tickers are labels, not identifiers; two
tokens can share all three.

`scripts/validate_evidence.py` rejects a finding whose `subject_address`
appears in none of its cited evidence. That catches the most common drift in
long investigations: a paragraph about contract A supported by a reading of
contract B, usually its implementation or its pool.

When a finding legitimately spans two addresses (a proxy and its
implementation, a token and its pool), cite evidence for both and say which
address the statement is about.

## Pinning: every state reading names its block

State without a block is not reproducible. Take the head block once, read
everything at that number, and put it in `block_pin`.

Record the block **hash** as well as the number. The hash is what lets a later
reader detect that a reorg replaced the block they are trying to reproduce.

Offchain sources cannot be block-pinned. They carry an observation timestamp
and a cache note instead, and they are marked `cached`, `unknown_cache`, or
`point_in_time`, never `block_pinned` and never `real_time`.

## Aggregate dashboards are not contract evidence

A TVL figure, a market cap, a holder count on a dashboard, or a yield number is
an aggregation performed by someone else, over an index you cannot see, at a
time you cannot pin. It is excellent for discovery and for sanity-checking an
order of magnitude.

It cannot support a `proven` or `strongly_supported` finding on its own. Use it
to find the pool, then read the pool. Use it to find the protocol, then read the
protocol's contracts.

`evidence.allow_dashboard_only_claims: false` enforces this. Turning it on is
allowed, and the report records that the standard was loosened.

## Falsifiers

Every finding above `unknown` names the observation that would overturn it.

| Weak | Useful |
| --- | --- |
| "more research could change this" | "the EIP-1967 admin slot reading as zero at the same block" |
| "if the team is honest" | "LP tokens held by a timelock contract rather than the deployer" |
| "unless the docs are wrong" | "a `redeem` entry point in the implementation ABI" |

A falsifier you cannot write means the claim is not yet a finding. It is either
a guess, or it is unfalsifiable, and both should be labelled honestly.

## Raw evidence

With `evidence.preserve_raw_evidence: true`, each onchain record keeps its raw
response, inline or as `raw_ref` into `evidence.raw_evidence_dir`. This is what
makes "re-check that reading" a two-second operation instead of a re-run.

Raw artifacts go through redaction before they are written. A cached response
that embeds the request URL will embed the credential too.

## Counterpoints

Every material finding carries the strongest argument against its importance.
Not a hedge, an argument.

- Upgradeable proxy: normal for a regulated issuer that must be able to patch a
  compliance bug. It is a control to locate, not a defect.
- Single liquidity provider: the normal starting state for any new token. It
  says nothing about intent.
- Concentrated holders: expected pre-distribution, and expected for a
  custodied asset where one address is the custodian.
- Pausable transfers: often a regulatory requirement, not a rug mechanism.

A report where every observation points the same way has usually stopped
looking. Writing the counterpoint is also the cheapest way to catch a finding
that does not survive it.

## Worked example

**Bad, and typical:**

> The token is safe. It has a large liquidity pool and the contract is verified
> on the explorer.

Three failures. "Safe" is a verdict, not a finding. "Large" is unbound and
unpinned. "Verified" is an explorer claim about source, which says nothing
about who can change the code.

**Better:**

> At block 4,812,345 the contract at `0x2173…5671` holds runtime code and is an
> EIP-1967 proxy: the implementation slot holds `0x887e…2b7c` and the admin
> slot holds `0x8EAa…926C`. Whoever controls the admin can replace the code,
> so every behavioural statement below describes the implementation in place at
> that block. *(proven, evidence EV-003, EV-004; falsified by both slots
> reading zero at the same block)*
>
> Counterpoint: upgradeability is standard for an issuer who has to be able to
> fix a compliance bug. The question is who the admin is, which is F-004.

## The validator is not optional

```bash
python3 scripts/validate_evidence.py research/report.json
```

Run it before writing prose, not after. Errors mean the report claims more than
it shows. Fix them by lowering confidence or gathering evidence. Deleting the
check is the one repair that is never correct.
