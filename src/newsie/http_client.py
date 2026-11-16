"""Shared HTTP client — honest user agent, per-source rate limit, robots.txt."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "Newsie/0.1 (+https://github.com/sacha-l/newsie)"

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}

_hits: dict[str, list[float]] = {}
_robots: dict[str, RobotFileParser | None] = {}


class FetchError(RuntimeError):
    def __init__(self, url: str, status_code: int | None, message: str) -> None:
        super().__init__(f"{message} ({url})")
        self.url = url
        self.status_code = status_code


def clear_fetch_limits() -> None:
    _hits.clear()
    _robots.clear()


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _enforce_rate(url: str, per_hour: int | None) -> None:
    if per_hour is None:
        return
    if per_hour < 1:
        raise FetchError(url, 429, "rate limit is zero")
    host = _host(url)
    now = time.monotonic()
    recent = [stamp for stamp in _hits.get(host, []) if now - stamp < 3600]
    if len(recent) >= per_hour:
        raise FetchError(url, 429, f"rate limit {per_hour}/h")
    recent.append(now)
    _hits[host] = recent


def _robots_allowed(url: str, http: httpx.Client) -> bool:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return True
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots:
        parser: RobotFileParser | None
        try:
            response = http.get(origin + "/robots.txt")
            if response.status_code != 200:
                parser = None
            else:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
        except httpx.HTTPError:
            parser = None
        _robots[origin] = parser
    parser = _robots[origin]
    if parser is None:
        return True
    return parser.can_fetch(USER_AGENT, url)


def fetch_text(
    url: str,
    *,
    timeout: float = 25.0,
    max_retries: int = 3,
    headers: dict[str, str] | None = None,
    client: httpx.Client | None = None,
    rate_limit_per_hour: int | None = None,
) -> str:
    """GET URL as text. Retries on 403/429/5xx with backoff. Obeys robots.txt."""
    merged = {**DEFAULT_HEADERS, **(headers or {})}
    owns = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout, headers=merged)
    last_exc: Exception | None = None
    try:
        _enforce_rate(url, rate_limit_per_hour)
        if not _robots_allowed(url, http):
            raise FetchError(url, 403, "blocked by robots.txt")
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
