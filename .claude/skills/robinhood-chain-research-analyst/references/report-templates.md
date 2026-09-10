# Report templates

Three depths, set by `research.report_depth`, overridden by whatever the user
asks for. All three share the same spine: answer the question, then the
findings that would change a decision, then what is not known, then evidence.

Two rules regardless of depth:

- **Answer first.** The user asked something. Answer it in the first two
  sentences, then support it. A report that makes the reader hunt for the
  answer has failed regardless of how good the research was.
- **The unknowns section is not optional and is never empty.** A report with no
  unknowns is a report that stopped looking.

## headline

Four to eight sentences. For a triage question or a quick check.

```markdown
**[Target]** on Robinhood Chain [mainnet|testnet], at block [N].

[Direct answer to the question asked, in one or two sentences.]

[The two or three findings that would most change a decision, each with its
confidence label and the address it is bound to.]

Not established: [the biggest gap, and why].

Research only. Not investment advice, a safety score, or an audit.
```

## standard

The default. One to two pages.

```markdown
# [Target] on Robinhood Chain

**Question.** [What the user asked, in their words.]
**Answer.** [Direct, two or three sentences, no hedging that does not carry
information.]

**As of** block [N] (`0x…hash`), [timestamp] UTC, chain id [4663|46630].
**Target** `0x…` [checksummed], resolved from "[what the user typed]".

## What matters

[Three to six findings, ordered by how much they would change a decision.
Each one:]

- **[Statement, specific enough to be checked.]** *(confidence, evidence ids)*
  [What it means for a holder, in one sentence.]
  Counterpoint: [the strongest argument that this matters less than it looks.]

## What is not established

- [Question that remains open, and what stopped it.]
- [Coverage limitation, what it prevented, and what would resolve it.]

## Coverage

[Which providers were usable and which were not, and what that cost. Rate
limits and missing credentials are limits on this run, not properties of the
target.]

Requests used [n] of [budget]. [What the next checks would cost.]

## Evidence

[Table: id, class, method, address, block, what it showed.]

---
Research only. Not investment advice, a price forecast, a safety score, or a
substitute for a full smart-contract audit. Controls identified here can change
the answer at any later block.
```

## full

`standard`, plus:

- a section per configured focus area, including the ones that found nothing;
- the complete evidence appendix with raw references;
- the full provider health table;
- a reproduction section: every command needed to re-derive the findings, with
  endpoints rendered host-only.

## The machine-checkable half

Alongside the prose, keep a bundle matching `schemas/report.schema.json`, and
validate it before the prose goes out:

```bash
python3 scripts/validate_evidence.py research/report.json
```

`assets/evidence_bundle_template.json` is a skeleton.
`fixtures/report_valid.json` is a filled-in synthetic example.

Writing the bundle first and the prose from it, rather than the reverse, is
what keeps the two consistent. Prose written first will always be more
confident than the evidence, because that is what prose does.

## Phrasing that keeps confidence honest

| Instead of | Write |
| --- | --- |
| "The contract is safe" | "No pause, blocklist, or mint authority was found in the implementation at block N. Unexamined code paths remain unexamined." |
| "Liquidity is locked" | "99.4 percent of LP supply sits at `0x…`, which is the token deployer. It can be withdrawn at will." |
| "Holders are well distributed" | "The top 10 non-contract holders hold 34 percent at block N. Three of them were funded by the same address." |
| "The team is anonymous" | "No identity claim was found. This was not researched further." |
| "Trading volume is strong" | "GeckoTerminal reported X in 24-hour volume, observed at [time], cached. Pool reserves at block N support a Y sale with Z percent impact." |
| "It looks like a scam" | "[The specific controls found], which together allow [the specific outcome]." |

The pattern: replace the adjective with the reading, name the block, name the
address, and let the reader draw the conclusion. That is also what makes a
report survive being wrong about something, because the reader can see which
part to re-check.
