"""Sina Finance HTTP helpers for SSE ETF options (stdlib only)."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://stock.finance.sina.com.cn/"


def _ssl_contexts() -> list[ssl.SSLContext]:
    contexts: list[ssl.SSLContext] = []
    try:
        import certifi  # type: ignore

        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    contexts.append(ssl.create_default_context())
    # macOS python.org builds often miss system CAs; last resort for public quotes
    unverified = ssl._create_unverified_context()
    contexts.append(unverified)
    return contexts


def http_get(url: str, *, referer: str = REFERER, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": referer,
            "Accept": "*/*",
        },
    )
    last_err: Exception | None = None
    for ctx in _ssl_contexts():
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except (urllib.error.URLError, ssl.SSLError) as exc:
            last_err = exc
            continue
    assert last_err is not None
    raise last_err


def http_get_text(url: str, *, encoding: str = "utf-8", **kwargs: Any) -> str:
    raw = http_get(url, **kwargs)
    for enc in (encoding, "gbk", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def http_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
    return json.loads(http_get_text(url, encoding="utf-8", **kwargs))


def parse_hq_vars(text: str) -> dict[str, list[str]]:
    """Parse `var hq_str_XXX="a,b,c";` blocks into {XXX: [fields]}."""
    out: dict[str, list[str]] = {}
    for m in re.finditer(r'var hq_str_([^=]+)="([^"]*)"', text):
        out[m.group(1)] = m.group(2).split(",")
    return out


def openapi(path: str, params: dict[str, str]) -> dict[str, Any]:
    qs = urllib.parse.urlencode(params)
    url = f"https://stock.finance.sina.com.cn/futures/api/openapi.php/{path}?{qs}"
    return http_get_json(url)
