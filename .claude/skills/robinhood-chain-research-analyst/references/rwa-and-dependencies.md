# Tokenized real-world assets, issuers, and outside dependencies

## The distinction that organises everything

A blockchain can enforce exactly two things about a token: who holds what
balance, and under what conditions a balance may move. Everything else a
tokenized real-world asset promises is a company's obligation, enforced by
contract law and reputation, not by the chain.

So every RWA report separates:

| The chain enforces | Someone promises |
| --- | --- |
| Balances and transfers | That an underlying asset exists |
| Who may transfer, if restrictions are coded | That it is held in segregated custody |
| Who may mint, burn, freeze, or pause | That you may redeem it |
| What an onchain redemption function does, if one exists | The price at which you may redeem |
| Which oracle address is configured | That the oracle reports honestly |

A report that blends these produces the single most misleading sentence in the
category: "the token is backed by X". Onchain, it is not backed by anything.
An issuer says it is. Both facts belong in the report, labelled differently.

## What to establish onchain

1. **Is there any onchain redemption at all?** Look for a `redeem`,
   `burnAndClaim`, `requestRedemption`, or settlement entry point in the
   implementation ABI. Usually there is not, and that absence is a finding.
2. **What restricts transfers?** Allowlists, blocklists, jurisdiction gates,
   lockup periods, maximum holdings, transfer agents. Read the transfer path
   in source, not just the selector list.
3. **Who can freeze or seize?** Many compliant RWA tokens include a forced
   transfer or clawback function. Whether that is appropriate is not the
   question; whether it exists and who holds it, is.
4. **Is supply elastic, and on what trigger?** Mint and burn authority tells
   you whether onchain supply tracks anything, or tracks a key.
5. **Is there an onchain attestation?** Some issuers publish reserve
   attestations to a contract. If so, read who can write to it and how often it
   has been updated. An attestation nobody has updated in six months is a
   finding.

## What to establish offchain, and label as claims

Read the issuer's own documentation and record, as claims:

- Who the issuer is and in what jurisdiction.
- Who holds the underlying asset, and whether custody is segregated.
- The redemption process: who is eligible, minimum size, fees, settlement
  window, and under what conditions it can be suspended.
- What attestation or audit exists, by whom, how often.
- What happens in insolvency: are holders creditors, beneficiaries, or neither.
- Which regulator, if any, and what that regime actually requires.

Every one of these is `inferred` at best, sourced from `documentation`-class
evidence. None can be `proven`. Say that plainly rather than letting a
confident tone imply verification.

## The questions a holder actually has

Answer these directly, in this order:

1. **Can I sell it?** Onchain sellability, from
   `sellability_and_exit_depth`. This is usually the real question.
2. **Can I redeem it?** Almost always an offchain process, with eligibility
   conditions the typical holder may not meet.
3. **What do I own if the issuer fails?** Usually the hardest question and
   usually unanswerable from onchain evidence. Say so.
4. **Who can stop me?** Freeze authority, pause authority, allowlist control.
5. **What is it worth if the oracle is wrong?** For anything that marks to an
   oracle, the oracle is part of the asset.

## Dependency checklist

Record every item as present, absent, or unchecked. "Unchecked" is a legitimate
answer and far better than an implied "fine".

### Oracles

- Which contract, read from the consuming contract's storage or getter.
- Who can update it, and can the oracle address itself be swapped.
- Heartbeat and deviation threshold; what a stale read does. A protocol that
  keeps quoting a stale price behaves very differently from one that halts.
- Single source or aggregated.
- Is the oracle chain-native or bridged from elsewhere.

### Bridges

- Canonical bridge or a third-party one.
- Who can mint the wrapped representation, and what backs it.
- If the asset arrived over a bridge, the bridge's security is the asset's
  security, whatever the token contract says.

### Sequencer and data availability

See `references/network.md`. For an exit-risk report: is there a delayed-inbox
escape if the sequencer censors, and how long does forced inclusion take.

### Custodians and issuers

- Named entity, jurisdiction, regulatory status as claimed.
- Attestation cadence and attestor.
- What onchain address, if any, represents them, and what powers it holds.

### Upstream protocols

Where a position depends on Morpho markets, a Lighter venue, or any other
protocol, corroborate state against that protocol's exact contracts or its
venue timestamps. A protocol's own dashboard is context; its contracts are
evidence.

### Off-chain APIs

Anything a redemption, a KYC gate, a price, or a mint depends on. If the API
goes away, what happens to the holder.

## Reporting shape

For an RWA target, the report has one extra section, placed before the
technical findings because it is what the reader is actually asking:

> **What you own.** Onchain, a transferable balance in contract `0x…`, subject
> to `[restrictions]`. There is no onchain redemption function. Redemption, as
> described by the issuer's published terms, is an offchain process requiring
> `[conditions]`, which the issuer can suspend under `[conditions]`. Whether
> that promise is honoured is not something any onchain check can establish.
>
> **What could change it.** `[dependency list]`.

Then the usual findings, unknowns, and evidence appendix.
