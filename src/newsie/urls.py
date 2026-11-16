"""Canonical article URLs — strip tracking parameters and follow rel=canonical."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

_TRACKING = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
}

_CANONICAL = re.compile(
    r"<link[^>]*rel=[\"']canonical[\"'][^>]*>",
    re.IGNORECASE,
)
_HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)


def canonicalise_url(url: str, html: str | None = None) -> str:
    """Return a stable URL. Tracking query keys are dropped. A canonical link wins."""
    if html:
        link = _CANONICAL.search(html)
        if link is not None:
            href = _HREF.search(link.group(0))
            if href is not None:
                url = urljoin(url, href.group(1).strip())
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), "")
    )
