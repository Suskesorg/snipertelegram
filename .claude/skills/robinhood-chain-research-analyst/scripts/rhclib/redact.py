"""Credential redaction for commands, logs, cached artifacts, errors, reports.

The rule this module enforces is narrow and absolute: a complete
credential-bearing URL never reaches a terminal, a log line, a cached file, or
a report. Everything the skill prints goes through `redact_text` or
`redact_obj` first, and endpoints taken from the environment are only ever
shown through `safe_endpoint`, which drops the credential-bearing part of the
path entirely rather than trying to mask it character by character.
"""

from __future__ import annotations

import os
import re

#: Environment variables whose *values* must never be printed. Matched on the
#: name, so a user-supplied alias like MY_ALCHEMY_TOKEN is covered too.
SECRET_NAME_PATTERN = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|BEARER|CREDENTIAL|PRIVATE|AUTH|SESSION)",
    re.IGNORECASE,
)

#: URLs are treated as secret-bearing as a whole when the variable names one.
URL_NAME_PATTERN = re.compile(r"(URL|ENDPOINT|URI)$", re.IGNORECASE)

_QUERY_SECRET_KEYS = (
    "apikey", "api_key", "api-key", "key", "token", "access_token", "auth",
    "authorization", "x-api-key", "secret", "password", "bearer", "sig",
    "signature", "session",
)

_QUERY_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(k) for k in _QUERY_SECRET_KEYS) + r")=([^&\s\"'`]+)"
)

_HEADER_RE = re.compile(
    r"(?i)(authorization|x-api-key|x-cg-pro-api-key|x-cg-demo-api-key|bearer)"
    r"(\s*[:=]\s*)([^\s\"'`,;]+)"
)

#: A path segment that looks like a credential: long, opaque, mixed alphabet.
_KEYISH_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_\-]{20,}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEXKEY_RE = re.compile(r"^[0-9a-fA-F]{32,}$")

#: Path segments that are structural, never credentials, and safe to show.
_SAFE_SEGMENTS = {
    "", "api", "v1", "v2", "v3", "rpc", "eth", "mainnet", "testnet", "public",
    "networks", "pools", "tokens", "coins", "onchain", "protocol", "protocols",
    "smart-contracts", "addresses", "transactions", "blocks", "search", "simple",
}

REDACTED = "[REDACTED]"


def _looks_like_credential(segment: str) -> bool:
    if segment.lower() in _SAFE_SEGMENTS:
        return False
    if segment.startswith("0x"):  # addresses and hashes are public identifiers
        return False
    return bool(_UUID_RE.match(segment) or _HEXKEY_RE.match(segment) or _KEYISH_RE.match(segment))


def collect_env_secrets(extra_names=()) -> dict:
    """Map secret value to the variable name it came from.

    Values shorter than 8 characters are skipped: they are more likely to be a
    flag like `true` than a credential, and redacting them would corrupt
    unrelated output.
    """
    secrets = {}
    names = list(os.environ.keys()) + [n for n in extra_names if n]
    for name in names:
        value = os.environ.get(name)
        if not value or len(value) < 8:
            continue
        if SECRET_NAME_PATTERN.search(name) and not URL_NAME_PATTERN.search(name):
            secrets[value] = name
        elif URL_NAME_PATTERN.search(name) and _url_has_credential(value):
            secrets[value] = name
    return secrets


def _url_has_credential(url: str) -> bool:
    if "@" in url.split("//", 1)[-1].split("/", 1)[0]:
        return True
    if _QUERY_RE.search(url):
        return True
    _, _, path, query = split_url(url)
    if query:
        return True
    return any(_looks_like_credential(seg) for seg in path.split("/"))


def split_url(url: str):
    """Return (scheme, host, path, query) without importing a URL parser's
    surprises. Anything unparseable comes back as all-empty, and callers treat
    that as 'not printable'."""
    if "://" not in url:
        return ("", "", "", "")
    scheme, rest = url.split("://", 1)
    hostpart, _, tail = rest.partition("/")
    if "@" in hostpart:  # strip userinfo, which may itself be a credential
        hostpart = hostpart.rsplit("@", 1)[1]
    path, _, query = tail.partition("?")
    return (scheme, hostpart, path, query)


def safe_endpoint(url: str) -> str:
    """Render an endpoint taken from configuration or the environment.

    Everything after the host is reduced to structural segments; the first
    credential-looking segment and everything after it is replaced. Query
    strings are dropped whole. The result is stable enough to tell two
    providers apart in a log and useless to anyone who copies it.
    """
    if not url or "://" not in url:
        return REDACTED
    scheme, host, path, query = split_url(url)
    if not host:
        return REDACTED
    shown = []
    for segment in path.split("/"):
        if segment == "":
            continue
        if _looks_like_credential(segment):
            shown.append(REDACTED)
            break
        shown.append(segment)
    rendered = "%s://%s" % (scheme, host)
    if shown:
        rendered += "/" + "/".join(shown)
    if query:
        rendered += "?" + REDACTED
    return rendered


def provider_label(url: str) -> str:
    """Host only. Use this in reports, where even a path is more than needed."""
    if not url or "://" not in url:
        return "unknown-host"
    return split_url(url)[1] or "unknown-host"


def redact_text(text, secrets=None) -> str:
    """Remove credentials from arbitrary text: env values, query parameters,
    auth headers, and credential-looking URL path segments."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    secrets = collect_env_secrets() if secrets is None else secrets
    for value, name in sorted(secrets.items(), key=lambda kv: -len(kv[0])):
        if value and value in text:
            text = text.replace(value, "[REDACTED:%s]" % name)
    text = _QUERY_RE.sub(lambda m: "%s=%s" % (m.group(1), REDACTED), text)
    text = _HEADER_RE.sub(lambda m: "%s%s%s" % (m.group(1), m.group(2), REDACTED), text)
    text = re.sub(r"https?://[^\s\"'`<>]+", lambda m: safe_endpoint(m.group(0)), text)
    return text


def redact_obj(obj, secrets=None):
    """Recursively redact a JSON-shaped structure before writing or printing it."""
    secrets = collect_env_secrets() if secrets is None else secrets
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if isinstance(key, str) and SECRET_NAME_PATTERN.search(key) and not URL_NAME_PATTERN.search(key):
                out[key] = REDACTED
            else:
                out[key] = redact_obj(value, secrets)
        return out
    if isinstance(obj, list):
        return [redact_obj(item, secrets) for item in obj]
    if isinstance(obj, str):
        return redact_text(obj, secrets)
    return obj


def assert_no_secrets(text, secrets=None) -> None:
    """Raise if a raw credential survived into text. Call this on anything
    about to be written to disk or handed to the user."""
    secrets = collect_env_secrets() if secrets is None else secrets
    for value, name in secrets.items():
        if value and value in str(text):
            raise AssertionError("credential from %s leaked into output" % name)
