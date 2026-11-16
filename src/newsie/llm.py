"""LLM provider interface. Stub returns no tokens and no prose the digest will trust."""

from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    token_usage: int

    def complete(self, system: str, user: str) -> str:
        """Return model text. Callers treat the result as untrusted."""


def call_tokens(provider: object) -> int:
    """Tokens for the most recent call.

    `last_call_tokens` is that call alone. `token_usage` is accepted when a
    provider only publishes a running total or the last response size.
    """
    last = getattr(provider, "last_call_tokens", None)
    if last is not None:
        return max(0, int(last))
    return max(0, int(getattr(provider, "token_usage", 0) or 0))


class StubLLMProvider:
    """Offline stand-in. Synthesis uses labelled claims, not this string."""

    token_usage: int = 0
    last_call_tokens: int = 0

    def complete(self, system: str, user: str) -> str:
        _ = (system, user)
        self.last_call_tokens = 0
        self.token_usage = 0
        return "stub"


class GrokProvider:
    """xAI chat completions. The reply is untrusted text, same as any other model."""

    def __init__(
        self,
        api_key: str,
        model: str = "grok-4",
        *,
        transport: object | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._transport = transport
        self.token_usage = 0
        self.last_call_tokens = 0

    def complete(self, system: str, user: str) -> str:
        import httpx

        with httpx.Client(timeout=60.0, transport=self._transport) as client:  # type: ignore[arg-type]
            response = client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        spent = int(usage.get("total_tokens") or 0)
        self.last_call_tokens = spent
        self.token_usage += spent
        choices = body.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        return content if isinstance(content, str) else ""
