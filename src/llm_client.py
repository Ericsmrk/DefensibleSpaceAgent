from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List


def _normalize_api_key(value: str | None) -> str | None:
    """Strip surrounding quotes and whitespace so .env quotes never break auth."""
    if value is None:
        return None
    s = (value or "").strip()
    if len(s) >= 2 and (s[0], s[-1]) in (('"', '"'), ("'", "'")):
        s = s[1:-1].strip()
    return s if s else None


class LLMClient:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model
        self.api_key = _normalize_api_key(os.getenv("OPENAI_API_KEY"))
        # Render (and similar proxies) often enforce ~30s request budgets; allow tuning per deploy.
        self.timeout_sec = 60
        raw_timeout = os.getenv("OPENAI_HTTP_TIMEOUT_SEC") or os.getenv("OPENAI_TIMEOUT_SEC")
        try:
            if raw_timeout and str(raw_timeout).strip():
                self.timeout_sec = int(float(raw_timeout))
            elif os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
                self.timeout_sec = 20
        except (TypeError, ValueError):
            self.timeout_sec = 60

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat_json(self, system: str, user: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_configured():
            return fallback

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)

    def chat_text(self, system: str, user: str, fallback: str) -> str:
        if not self.is_configured():
            return fallback
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
