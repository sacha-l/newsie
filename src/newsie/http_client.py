"""Shared HTTP client — browser-like headers + retries for 403/429."""

from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Newsie/0.1; +https://github.com/sacha-l/newsie) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}


class FetchError(RuntimeError):
    def __init__(self, url: str, status_code: int | None, message: str) -> None:
        super().__init__(f"{message} ({url})")
        self.url = url
        self.status_code = status_code


def fetch_text(
    url: str,
    *,
    timeout: float = 25.0,
    max_retries: int = 3,
    headers: dict[str, str] | None = None,
    client: httpx.Client | None = None,
) -> str:
    """GET URL as text. Retries on 403/429/5xx with backoff."""
    merged = {**DEFAULT_HEADERS, **(headers or {})}
    owns = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout, headers=merged)
    last_exc: Exception | None = None
    try:
        for attempt in range(max_retries):
            try:
                resp = http.get(url)
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(0.4 * (attempt + 1))
                continue
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in {403, 429, 500, 502, 503, 504} and attempt + 1 < max_retries:
                # Some CDNs soft-block first hit; brief backoff + retry
                time.sleep(0.6 * (attempt + 1))
                continue
            raise FetchError(url, resp.status_code, f"HTTP {resp.status_code}")
        if last_exc is not None:
            raise FetchError(url, None, f"network error: {last_exc}") from last_exc
        raise FetchError(url, None, "fetch failed")
    finally:
        if owns:
            http.close()


def fetch_bytes(url: str, **kwargs: Any) -> bytes:
    return fetch_text(url, **kwargs).encode("utf-8", errors="replace")
