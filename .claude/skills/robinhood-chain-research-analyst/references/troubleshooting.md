# Troubleshooting: is this a coverage limitation or a finding?

The distinction this file exists for: **a limit on your ability to look is
never a fact about the thing you were looking at.** Getting this backwards
produces reports that are confidently, invisibly wrong.

| Observation | This is | What to write |
| --- | --- | --- |
| HTTP 429 from the explorer | Coverage limitation | "The holder list could not be retrieved. Concentration is unmeasured." |
| HTTP 401 or 403 from a provider | Coverage limitation | "This capability requires a credential that is not configured." |
| A bot-protection challenge page | Coverage limitation | "This host serves a human-verification challenge. It cannot be used unattended." |
| Provider does not index this chain | Coverage limitation | "No coverage for this network from this provider." Never substitute another chain |
| Timeout or DNS failure | Coverage limitation | "Endpoint unreachable during this run." |
| `proxy_denied_403` from every host | Coverage limitation, **local** | "This environment's egress proxy refused the connection. The providers were never reached." Never report it as a provider outage |
| Historical query fails without an archive endpoint | Coverage limitation | "Historical state was not available." |
| `eth_getCode` returns `0x` | **Finding** | "No contract code at this address at block N." |
| `eth_call` reverts from a real holder | **Finding** | "The call reverts. [Reason if returned.]" |
| A storage slot reads zero | **Finding** | "The slot is empty at block N." |
| A log scan of a stated range returns nothing | **Finding, scoped** | "No such events between blocks A and B." Name the range |
| Explorer reports the contract as unverified | **Finding** | "Source is not published. Behavioural claims are limited to what bytecode and storage show." |
| A provider returns a different number than another | Neither, yet | Record both, compare bases, leave it visible |

## Common failures and what to do

### The chain id does not match

Stop. Do not continue and mention it later. Either the endpoint is wrong, the
configuration is wrong, or the documented value has changed. Report which of
those you can establish. `scripts/verify_network.py` exits 2 for this case.

### Every provider fails at once

Almost always your side, not theirs. `proxy_denied_403`, `tls_error` on every
host, or an identical failure across unrelated providers points at a corporate
proxy, a firewall, or a missing CA bundle. `scripts/check_providers.py`
separates this case out and says the provider was never reached, because the
alternative is a report claiming that five independent services are
simultaneously down.

Fix the egress path, then re-run. Until then every finding that needed the
network is `unavailable`, and the report says the limitation was local.

### Everything is rate limited

The public endpoints are shared. Options, in order: reduce scope to the highest
value checks, wait out the window, or configure a credential. Do not retry in a
loop; `research.max_failed_attempts_per_check` exists to stop exactly that.
Report what you got and what it would take to get the rest.

### A log query returns nothing, or exactly the maximum

Nothing may be true, or the range may be wrong. Confirm the contract existed in
that range. Exactly the provider's maximum result count almost always means
truncation: split the range and re-query. Never conclude "no events" from a
possibly-truncated response.

### The explorer and the chain disagree

The chain wins for state. The explorer is an index that can lag, mis-detect a
proxy, or serve a cached page. Record both, and say which you relied on.

### The implementation is not verified

You can still read storage, call getters, and observe behaviour. What you
cannot do is enumerate privileged functions with confidence. Say that: "the
implementation is unverified, so this list of privileged functions is derived
from selectors present in the bytecode and may be incomplete."

### An `eth_call` reverts and you cannot tell why

Check, in order: wrong selector, wrong argument encoding, function does not
exist on this contract, function is admin-only, contract is paused, or the
`from` address fails a check. The last three are findings. The first three are
your mistake. Distinguish them before writing either down.

### A number looks wrong by a factor of 10 to the something

Decimals. Read `decimals()` and convert explicitly. This is the most common
arithmetic error in onchain research, and it produces answers that are wrong by
orders of magnitude while looking entirely plausible.

### The budget ran out mid-investigation

Report what is established, what is open, and what the next checks would cost.
Then ask. This is a good outcome, not a failure. The bad outcome is spending
ten times the budget silently, or filling the gap with narrative.

### PyYAML is not installed

The configuration loader falls back to a parser covering the shapes in
`config.example.yaml`. If your file uses something it does not support, it
names the line and suggests installing PyYAML rather than guessing.

### The validator rejects a bundle you believe is right

Read the error; it names the rule and the setting behind it. Then either
lower the confidence, gather the evidence, or deliberately relax the setting in
configuration, which the report will record. Do not edit the validator.

## Self-check

```bash
python3 scripts/selfcheck.py
```

Runs the whole offline suite: hash vectors, redaction, configuration parsing
with and without PyYAML, all four provider health states, every evidence rule,
and the shipped fixtures. No network access, no live investigation.
