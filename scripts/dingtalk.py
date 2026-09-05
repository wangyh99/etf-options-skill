"""DingTalk custom robot delivery with optional HMAC signing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

from report_html import format_dingtalk_markdown


def build_webhook(config: dict, timestamp_ms: int | None = None) -> str:
    webhook = str(config.get("webhook") or "").strip()
    token = str(config.get("access_token") or "").strip()
    if not webhook:
        if not token:
            raise ValueError("DingTalk webhook or access_token is required")
        webhook = (
            "https://oapi.dingtalk.com/robot/send?access_token="
            + urllib.parse.quote(token, safe="")
        )
    secret = str(config.get("secret") or "").strip()
    if not secret:
        return webhook
    timestamp = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
    string_to_sign = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(secret.encode(), string_to_sign, hashlib.sha256).digest()
    sign = base64.b64encode(digest).decode()
    separator = "&" if "?" in webhook else "?"
    return (
        f"{webhook}{separator}timestamp={timestamp}"
        f"&sign={urllib.parse.quote_plus(sign)}"
    )


def send_markdown(title: str, markdown: str, config: dict, timeout: int = 15) -> dict:
    url = build_webhook(config)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": markdown},
        "at": {"isAtAll": False},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"DingTalk request failed: {type(exc).__name__}") from exc
    if int(result.get("errcode", -1)) != 0:
        raise RuntimeError(f"DingTalk rejected message: {result.get('errmsg', 'unknown error')}")
    return result


def send_report(report: dict, config: dict) -> dict:
    strategy = "铁鹰" if report.get("strategy") == "iron_condor" else "宽跨"
    return send_markdown(f"ETF期权{strategy}策略", format_dingtalk_markdown(report), config)
