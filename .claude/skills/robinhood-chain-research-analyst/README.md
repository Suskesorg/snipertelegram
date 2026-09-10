# robinhood-chain-research-analyst

An agent skill that turns a general-purpose assistant into a configurable,
evidence-bounded research analyst for **Robinhood Chain** (EVM-compatible
Arbitrum layer 2, mainnet chain id `4663`, testnet `46630`).

Give it an address, a transaction, a pool, a protocol, a wallet, or a question,
and it produces an answer where every claim is pinned to a block, bound to an
exact address, and labelled `proven`, `strongly_supported`, `inferred`,
`unknown`, or `unavailable`.

It works with **no API keys at all** and improves when Alchemy, dRPC,
CoinGecko, or DeFiLlama credentials are configured.

It is not a trading bot, a price predictor, a safety score, a legal opinion, an
investment recommendation, or a substitute for a smart-contract audit.

## Install

The package is a plain directory: `SKILL.md` plus `references/`, `scripts/`,
`schemas/`, `assets/`, `fixtures/`, and `tests/`. Nothing is host-specific, so
the same directory works in several places.

### Claude Code, this project

Already installed if this directory sits at
`.claude/skills/robinhood-chain-research-analyst/`. It loads for anyone working
in the repository.

### Claude Code, all your projects

```bash
cp -r .claude/skills/robinhood-chain-research-analyst ~/.claude/skills/
```

### Claude desktop or claude.ai

Package the directory as a `.skill` file (a zip with the skill folder at its
root) and upload it:

```bash
cd .claude/skills
zip -r robinhood-chain-research-analyst.skill robinhood-chain-research-analyst \
    -x '*__pycache__*' '*.pyc'
```

If you have the `skill-creator` skill available, its packager validates the
frontmatter first, which is worth the extra step:

```bash
python3 <path-to>/skill-creator/scripts/package_skill.py \
    .claude/skills/robinhood-chain-research-analyst ./dist
```

### Any other agent

There is nothing proprietary in the format. Point the agent at `SKILL.md` as
its instructions and give it filesystem and shell access to this directory.
Every path in the package is relative to the skill root and resolved from
`__file__`, so the scripts run from any working directory.

## Quick start

```bash
cd .claude/skills/robinhood-chain-research-analyst

python3 scripts/selfcheck.py        # prove the helpers work, no network needed
python3 scripts/validate_config.py  # what the analyst will actually do
python3 scripts/check_providers.py  # what is usable right now
python3 scripts/verify_network.py   # chain id and head block
```

Then ask the assistant something like:

> Look at `0x…` on Robinhood Chain. Who controls it, and could I sell 10k?

## Configuration

Optional. Copy the example and edit your copy:

```bash
cp config.example.yaml robinhood-chain.config.yaml
python3 scripts/validate_config.py --config robinhood-chain.config.yaml
```

Every option is documented inline in `config.example.yaml`, and
`schemas/config.schema.json` describes what each one accepts. You can change
report depth, risk posture, focus areas, exit sizes, time and request budgets,
evidence strictness, and provider preferences without touching `SKILL.md`.

Unknown keys are rejected rather than ignored, with a suggestion for the key
you probably meant. A typo that silently leaves a default in place is worse
than an error.

**Your instructions in a request always beat the configuration file.** The
settings only decide what happens when a request is silent.

Search order: `--config`, then `$ROBINHOOD_CHAIN_ANALYST_CONFIG`, then
`./robinhood-chain.config.yaml`, then
`~/.config/robinhood-chain-research-analyst/config.yaml`, then the shipped
example.

## Credentials

All optional, all from the environment, never from a file:

```bash
export ROBINHOOD_RPC_URL="https://..."           # preferred RPC
export ROBINHOOD_ARCHIVE_RPC_URL="https://..."   # historical state
export ROBINHOOD_SECONDARY_RPC_URL="https://..." # independent corroboration
export ALCHEMY_API_KEY="..."                     # plus alchemy_url_template
export DRPC_URL="https://..."                    # or DRPC_API_KEY
export COINGECKO_API_KEY="..."
export DEFILLAMA_API_KEY="..."
export X_BEARER_TOKEN="..."
export TRADITIONAL_MARKET_DATA_API_KEY="..."
```

Already have these under different names? Map them in
`providers.env_aliases` instead of renaming your variables.

Alchemy and dRPC endpoints are deliberately **not** guessed: both embed the
credential in the URL and both change their per-chain host format. Read the
current format from the provider's documentation and put it in
`providers.alchemy_url_template` or `providers.drpc_url_template`, with `{key}`
where the credential goes.

Credentials are redacted from commands, logs, cached artifacts, errors, and
reports. A complete credential-bearing URL is never printed. To confirm a file
is clean:

```bash
python3 scripts/redact_stream.py --check < research/report.md
```

## What is in here

| Path | What it is |
| --- | --- |
| `SKILL.md` | The analyst's instructions. Start here |
| `config.example.yaml` | Documented settings template |
| `references/` | The research method: network, providers, evidence rules, playbooks, RPC recipes, RWA guidance, report templates, troubleshooting |
| `schemas/` | JSON Schemas for the configuration, evidence records, findings, and report bundles |
| `scripts/` | Working helpers: config validation, provider health, network verification, evidence validation, selector and slot computation, redaction, self-check |
| `assets/` | Report and evidence-bundle templates to fill in |
| `fixtures/` | Synthetic test data. Nothing here was read from any chain |
| `tests/` | The offline test suite, run by `scripts/selfcheck.py` |

## Requirements

Python 3.8 or newer. **No third-party packages are required.** PyYAML is used
when present and a built-in parser covers the configuration format when it is
not, so the helpers run on a bare interpreter.

Keccak-256, EIP-55 checksums, function selectors, event topics, and proxy
storage slots are all computed from first principles in
`scripts/rhclib/crypto.py`, and pinned to published test vectors in
`tests/test_crypto.py`. Nothing depends on a memorised constant.

## Verifying the package

```bash
python3 scripts/selfcheck.py
```

Runs 100-plus tests with no network access: hash vectors, EIP-55 vectors,
redaction, configuration parsing with and without PyYAML, all four provider
health states, every evidence rule, and both shipped fixture bundles. Then it
re-validates the shipped artifacts independently of the tests.

## Scope

This skill answers due-diligence questions: what a contract is, who controls
it, whether it can be upgraded or paused, where the liquidity is and who owns
it, whether an ordinary holder can realistically sell, how concentrated
ownership is, where fees and reserves go, what a tokenized real-world asset
actually entitles a holder to, and which outside dependency could change any of
it.

It declines to produce verdict words, safety scores, price predictions, buy or
sell recommendations, or legal conclusions, and it says plainly that unexamined
code paths remain unexamined.
