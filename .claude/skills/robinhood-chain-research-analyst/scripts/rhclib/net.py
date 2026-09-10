"""HTTP and JSON-RPC transport with request budgets and no credential leakage.

Standard library only. Two things here matter more than the plumbing:

* Every error is mapped to a small vocabulary of *transport* outcomes. A
  timeout, a DNS failure, a 429 and a bot-protection challenge are different
  facts about the world, and collapsing them into "offline" would turn a
  coverage limitation into a false finding about the target.
* Response bodies are never returned to callers that print. A short,
  redacted head is kept for classification only, and the classifier reads
  markers out of it rather than passing it along.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import redact

USER_AGENT = "robinhood-chain-research-analyst/1.0 (+read-only research helper)"

#: How much of a response we keep for classification. Enough to spot a
#: challenge page, too little to be a useful data leak.
CLASSIFY_HEAD_BYTES = 512


class BudgetExceeded(Exception):
    """Raised when a run hits the configured provider request budget."""


class RequestBudget:
    """Counts provider requests and operations against the configured caps.

    Two counters, because they answer different questions: `requests` is how
    many times we touched a provider (rate-limit and politeness budget) and
    `operations` is how many distinct research steps those requests served
    (scope budget). A single paginated log scan is many requests and one
    operation.
    """

    def __init__(self, max_requests=30, max_operations=100, max_failures_per_check=2):
        self.max_requests = max_requests
        self.max_operations = max_operations
        self.max_failures_per_check = max_failures_per_check
        self.requests = 0
        self.operations = 0
        self.failures = {}

    def spend_request(self, amount=1):
        if self.requests + amount > self.max_requests:
            raise BudgetExceeded(
                "provider request budget exhausted (%d of %d used). Report what is "
                "established so far, list what is still unknown, and ask before "
                "extending the budget." % (self.requests, self.max_requests))
        self.requests += amount

    def spend_operation(self, amount=1):
        if self.operations + amount > self.max_operations:
            raise BudgetExceeded(
                "provider operation budget exhausted (%d of %d used)."
                % (self.operations, self.max_operations))
        self.operations += amount

    def record_failure(self, check: str) -> bool:
        """Return True when this check has failed too often to retry again."""
        self.failures[check] = self.failures.get(check, 0) + 1
        return self.failures[check] >= self.max_failures_per_check

    def snapshot(self) -> dict:
        return {
            "requests_used": self.requests,
            "requests_budget": self.max_requests,
            "operations_used": self.operations,
            "operations_budget": self.max_operations,
            "checks_abandoned": sorted(k for k, v in self.failures.items()
                                       if v >= self.max_failures_per_check),
        }


class HttpOutcome:
    """A transport-level result. Carries no full body by design."""

    __slots__ = ("status", "error_kind", "detail", "head", "content_type",
                 "retry_after", "latency_ms", "host_responded", "server")

    def __init__(self, status=None, error_kind=None, detail="", head="",
                 content_type="", retry_after=None, latency_ms=None, server=""):
        self.status = status
        self.error_kind = error_kind
        self.detail = detail
        self.head = head
        self.content_type = content_type
        self.retry_after = retry_after
        self.latency_ms = latency_ms
        self.server = server
        self.host_responded = status is not None

    def json(self):
        """Parse the retained head as JSON, or return None. Used for small
        RPC replies only; large payloads are re-fetched by callers that need
        the whole body and know what they are doing with it."""
        try:
            return json.loads(self.head)
        except Exception:
            return None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def http_request(url, method="GET", body=None, headers=None, timeout=20,
                 budget=None, max_body_bytes=1 << 20) -> HttpOutcome:
    """Perform one HTTP request and classify the transport outcome.

    Never raises for HTTP status or network failure: the outcome object carries
    the fact. It raises only for a budget violation, which is a decision the
    caller asked for.
    """
    if budget is not None:
        budget.spend_request()
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    payload = body.encode("utf-8") if isinstance(body, str) else body
    request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_body_bytes)
            return HttpOutcome(
                status=response.status,
                head=_head(raw),
                content_type=response.headers.get("Content-Type", ""),
                server=response.headers.get("Server", ""),
                retry_after=response.headers.get("Retry-After"),
                latency_ms=_ms(started),
            )
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(CLASSIFY_HEAD_BYTES * 4)
        except Exception:
            raw = b""
        return HttpOutcome(
            status=exc.code,
            head=_head(raw),
            content_type=exc.headers.get("Content-Type", "") if exc.headers else "",
            server=exc.headers.get("Server", "") if exc.headers else "",
            retry_after=exc.headers.get("Retry-After") if exc.headers else None,
            latency_ms=_ms(started),
            detail="http %d" % exc.code,
        )
    except urllib.error.URLError as exc:
        return HttpOutcome(error_kind=_url_error_kind(exc),
                           detail=redact.redact_text(str(getattr(exc, "reason", exc)))[:160],
                           latency_ms=_ms(started))
    except Exception as exc:  # socket timeouts and anything unexpected
        kind = "timeout" if "timed out" in str(exc).lower() else "transport_error"
        return HttpOutcome(error_kind=kind,
                           detail=redact.redact_text(str(exc))[:160],
                           latency_ms=_ms(started))


def _ms(started):
    return int((time.time() - started) * 1000)


def _head(raw: bytes) -> str:
    try:
        return raw[:CLASSIFY_HEAD_BYTES * 8].decode("utf-8", errors="replace")
    except Exception:
        return ""


def _url_error_kind(exc) -> str:
    reason = str(getattr(exc, "reason", exc)).lower()
    if "timed out" in reason or "timeout" in reason:
        return "timeout"
    if "certificate" in reason or "ssl" in reason or "tls" in reason:
        return "tls_error"
    if "name or service not known" in reason or "nodename nor servname" in reason \
            or "getaddrinfo" in reason or "temporary failure in name resolution" in reason:
        return "dns_failure"
    # An egress proxy that answers and refuses is a gate, not a dead host. The
    # remedy is a network policy change, so it must not read as "provider down".
    if "tunnel connection failed" in reason or "proxy" in reason:
        status = re.search(r"\b(4\d\d|5\d\d)\b", reason)
        return "proxy_denied_%s" % status.group(1) if status else "proxy_error"
    if "refused" in reason or "unreachable" in reason or "reset" in reason:
        return "connect_error"
    return "transport_error"


def json_rpc(url, method, params=None, timeout=20, budget=None, request_id=1):
    """Send one JSON-RPC call. Returns (outcome, parsed_payload_or_None)."""
    body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                       "params": params or []})
    outcome = http_request(url, method="POST", body=body,
                           headers={"Content-Type": "application/json"},
                           timeout=timeout, budget=budget)
    return (outcome, outcome.json())


def hex_to_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.startswith("0x"):
        try:
            return int(value, 16)
        except ValueError:
            return None
    return None
