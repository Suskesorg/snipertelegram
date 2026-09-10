# Providers: tiers, capabilities, health, and disagreement

## The two tiers

### Tier 1, zero-key starter mode

Runs with no credentials at all. Subject to availability and rate limits:

| Source | Serves | Trust it for |
| --- | --- | --- |
| Robinhood Chain public RPC | State, blocks, receipts, calls, code, storage, bounded log queries | Current onchain state. This is the authority |
| Robinhood Chain Blockscout | Contract discovery, verified source, ABI, transactions | Finding things and reading source. Verify material claims against the deployed runtime |
| GeckoTerminal public API | DEX pools, liquidity, trades, OHLCV | Discovering where a token trades |
| CoinGecko public endpoints | Market context, asset metadata | Context. Bind anything material to an address |
| DeFiLlama public endpoints | Protocol TVL, fees, revenue, yields, categories | Protocol-level context, never contract-level proof |
| Morpho and Lighter public read-only endpoints | Protocol positions and venue state | Corroborate against exact contracts or venue timestamps |
| Official documentation | Architecture, claimed behaviour | What is *claimed*. Never what *happens* |

Starter mode stays useful when several of these are unavailable. It degrades by
narrowing what can be claimed, not by inventing substitutes.

### Tier 2, configured research mode

Adds whatever credentials are present. Nothing here is required, and no finding
should depend on a paid service existing.

| Variable | Capability | Notes |
| --- | --- | --- |
| `ROBINHOOD_RPC_URL` | Preferred RPC | Replaces the public endpoint |
| `ROBINHOOD_ARCHIVE_RPC_URL` | Historical state, long log scans | Prove it is really archive before trusting it |
| `ROBINHOOD_SECONDARY_RPC_URL` | Independent corroboration | Ideally a different operator, not a second URL for the same node |
| `ALCHEMY_API_KEY` | Enhanced RPC | Endpoint format must come from current Alchemy documentation |
| `DRPC_URL` or `DRPC_API_KEY` | Enhanced RPC | Same rule, per dRPC's current format |
| `COINGECKO_API_KEY` | Market and onchain DEX coverage | Higher limits and more endpoints |
| `DEFILLAMA_API_KEY` | Paid protocol coverage | |
| `X_BEARER_TOKEN` | Reproducible social sampling | Without it, results are search-visible narrative |
| `TRADITIONAL_MARKET_DATA_API_KEY` | Licensed equities and reference data | Aliases supported for whatever your provider calls it |

Map names you already use with `providers.env_aliases` rather than renaming
your environment variables.

## Why endpoints are never guessed

`providers.alchemy_url_template` and `providers.drpc_url_template` ship empty on
purpose. Both providers embed the credential in the URL and both change their
per-chain host format. A guessed URL fails in one of two ways: it errors in a
way that looks like the chain is down, or it succeeds against a *different
chain* and every reading is quietly wrong.

So: read the provider's current documentation, then set the template with
`{key}` where the credential goes. `scripts/check_providers.py` will tell you a
credential is set but the template is missing, rather than inventing a host.

## Capability routing

Pick a provider for what it can prove, not for its name.

| Question | Authority | Corroborate with |
| --- | --- | --- |
| What is the state right now | Raw RPC at a pinned block | A second RPC for anything surprising |
| What was the state then | Archive RPC | Explorer history, if it agrees |
| What is this contract, is it verified | Blockscout | `eth_getCode` for the deployed runtime |
| Where does this token trade | GeckoTerminal, CoinGecko | Pool contract reads at the pinned block |
| How deep is the liquidity really | Pool contract reads | Aggregator figures, as a sanity check |
| How big is this protocol | DeFiLlama | Contract reads for anything load-bearing |
| What does the team claim | Documentation | Onchain behaviour, which may differ |
| What are people saying | X API with a token | Nothing. This is narrative, always |

The ordering rule: **discovery may come from anywhere, proof comes from the
chain.** Aggregators are excellent at telling you a pool exists and terrible at
telling you what it contains right now.

## Health states

`scripts/check_providers.py` classifies each provider into exactly one of four
states. The distinctions are load-bearing.

| State | Means | What it does to the report |
| --- | --- | --- |
| `available` | Host answered, capability worked | Usable |
| `reachable_but_restricted` | Host answered and gated us: 401, 403, 429, plan limit, method not supported, or a bot-protection challenge | Coverage limitation. Findings that needed it become `unavailable` |
| `chain_mismatch` | Host answered about a different chain, or does not index this one | Coverage limitation. Never substitute the other chain |
| `unavailable` | No usable answer: DNS, connection, TLS, timeout, 5xx, or nothing configured | Coverage limitation |

An HTTP 401, 403, or 429 proves a host responded. It does not prove the
capability is usable, and it says nothing at all about the target. Record the
status class. Never record a response body, and never record a credential.

Bot protection and rate limiting keep their own reasons and are never collapsed
into a generic offline result, because the remedies differ: a rate limit means
wait, a challenge means this path will not work unattended, and a real outage
means try another provider.

## Freshness: three separate facts

Never merge these:

1. **Observation timestamp**: when you made the request.
2. **Provider cache behaviour**: what the provider documents about staleness,
   or, honestly, that it documents nothing.
3. **Pinned block**: the block an onchain reading describes.

A REST response is never "real time". `scripts/validate_evidence.py` rejects an
aggregator record labelled `real_time`, because that label is how a
five-minute-old cached number becomes a statement about the current market.

## When providers disagree

Preserve both observations. Then:

1. **Compare bases.** Different block heights, different time windows, or one
   figure quoted in a different unit explain most disagreements.
2. **Ask which one could actually know.** A node reading its own state and an
   aggregator reading its own index are not equally authoritative about state.
3. **Re-read at an explicit block** from both, rather than at `latest`.
4. **If it survives all that, leave it unresolved and visible.** Record both
   under `provider_disagreement` and lower the confidence.

Silently picking the number that fits the narrative is the single most damaging
thing a research agent can do, precisely because the result looks clean.

## Social sources

Without `X_BEARER_TOKEN`: whatever web search surfaces is **search-visible
narrative**. It is shaped by ranking, recency, and SEO. Label it as such, never
as sentiment, and never quantify it.

With a token: sampling is reproducible within `research.sentiment_window_hours`
and capped at `research.social_sample_limit`. Record the query, the window, and
the cap, so the sample can be re-drawn. It is still narrative. Social consensus
is not evidence about a contract, and a coordinated campaign looks exactly like
organic enthusiasm from the inside.

Both ways, social material can only support findings in
`narrative_and_sentiment`, never in a technical focus area.
