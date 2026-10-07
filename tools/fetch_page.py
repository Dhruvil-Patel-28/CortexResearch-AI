"""
Page fetcher — turns a search hit into readable article text.

Search snippets alone produce shallow reports, so the researcher pulls the top
pages it found and extracts the main body. Extraction is heuristic (lxml only,
no extra dependency beyond what is already installed): prefer <article>/<main>,
fall back to the densest container by paragraph text, then to all text.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from lxml import html as lxml_html

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 CortexResearch/2.0"
)
_STRIP_TAGS = ("script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "iframe", "figure")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANKS_RE = re.compile(r"\n{3,}")


def fetch_page_text(url: str, *, timeout: float = 10.0, max_chars: int = 7000) -> str:
    """
    Fetch a URL and return cleaned main-body text ("" on any failure).

    Never raises: a dead link simply contributes no text to the evidence.
    Output is guardrail-sanitized (PII scrub + injection neutralization).
    """
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            response = client.get(url)
        if response.status_code >= 400:
            logger.debug("fetch %s → HTTP %s", url, response.status_code)
            return ""
        content_type = response.headers.get("content-type", "")
        if content_type and not any(t in content_type for t in ("html", "text", "xml")):
            return ""
        from guardrails import sanitize_content

        text, _ = sanitize_content(extract_main_text(response.text, max_chars=max_chars))
        return text
    except Exception as e:  # noqa: BLE001 — network errors are expected on the open web
        logger.debug("fetch failed for %s: %s", url, e)
        return ""


def extract_main_text(html: str, *, max_chars: int = 7000) -> str:
    """Extract the readable body from raw HTML."""
    if not html:
        return ""
    try:
        doc = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 — malformed markup
        return _clean(html, max_chars)

    for tag in _STRIP_TAGS:
        for node in doc.xpath(f"//{tag}"):
            node.drop_tree()

    best = ""
    for candidate in doc.xpath("//article | //main | //div"):
        paragraphs = candidate.xpath(".//p//text()")
        text = _clean(" ".join(paragraphs))
        if len(text) > len(best):
            best = text
        if len(best) >= max_chars:
            break

    if len(best) < 500:
        body = doc.find("body")
        fallback = _clean(body.text_content() if body is not None else doc.text_content())
        if len(fallback) > len(best):
            best = fallback

    return best[:max_chars]


def _clean(text: str, max_chars: int = 7000) -> str:
    text = _WS_RE.sub(" ", text or "")
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANKS_RE.sub("\n\n", text).strip()[:max_chars]


def fetch_many(urls: list[str], *, timeout: float = 10.0, max_chars: int = 7000) -> dict[str, str]:
    """Fetch several URLs concurrently (bounded), returning {url: text}."""
    from concurrent.futures import ThreadPoolExecutor

    unique: list[str] = []
    for url in urls:
        if url and url not in unique:
            unique.append(url)
    if not unique:
        return {}

    out: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_page_text, url, timeout=timeout, max_chars=max_chars): url for url in unique}
        for future, url in futures.items():
            try:
                out[url] = future.result(timeout=timeout + 5)
            except Exception:  # noqa: BLE001
                out[url] = ""
    return out


def summarise_source_quality(text: Optional[str]) -> str:
    """Rough quality label used in logs/trace."""
    if not text:
        return "none"
    if len(text) > 2000:
        return "full"
    if len(text) > 600:
        return "partial"
    return "thin"
