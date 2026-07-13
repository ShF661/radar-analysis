"""Feishu webhook push (text card only)."""
from __future__ import annotations

import json
import time
import urllib.request


def push(webhook_url: str, text: str, retries: int = 3) -> None:
    """POST a plain text message to a Feishu bot webhook. Retries on failure."""
    payload = json.dumps({"msg_type": "text", "content": {"text": text}}).encode("utf-8")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                result = json.loads(body)
                if result.get("code") == 0 or result.get("StatusCode") == 0:
                    return
                raise RuntimeError(f"Feishu API error: {result}")
        except Exception as e:
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
