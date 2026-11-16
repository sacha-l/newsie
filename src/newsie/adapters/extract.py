"""Article text extraction. trafilatura when it is installed, otherwise a bounded HTML dump.

A short visible body on a long page is marked partial. Claims stop at that text.
"""

from __future__ import annotations

from bs4 import BeautifulSoup


def extract_article(html: str) -> tuple[str, str, str, bool]:
    """Return title, visible text, method name, and whether the text is partial."""
    title, text, method = _trafilatura(html)
    if not text:
        title, text = _beautifulsoup(html)
        method = "beautifulsoup"
    partial = False
    if len(text) < 400 and len(html) > 5_000:
        partial = True
    if len(text) > 20_000:
        text = text[:20_000]
        partial = True
    return title, text, method, partial


def _trafilatura(html: str) -> tuple[str, str, str]:
    try:
        import trafilatura
    except ImportError:
        return "", "", ""
    text = trafilatura.extract(html, include_comments=False) or ""
    meta = trafilatura.extract_metadata(html)
    title = ""
    if meta is not None and meta.title:
        title = str(meta.title).strip()
    return title, text.strip(), "trafilatura"


def _beautifulsoup(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "aside"]):
        tag.decompose()
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    heading = soup.find("h1")
    if heading and heading.get_text(strip=True):
        title = heading.get_text(strip=True) or title
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = root.get_text("\n", strip=True) if root else ""
    return title, text
