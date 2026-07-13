"""Shared HTML parsing helpers for crawlers.

Uses BeautifulSoup (pure-python, always available). A crawler's *selectors*
live at the top of its own module; this file only holds generic utilities so
selector fixes stay localized to one source.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def text(node) -> str:  # noqa: ANN001
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def attr(node, name: str) -> Optional[str]:  # noqa: ANN001
    if node is None:
        return None
    v = node.get(name)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def first(parent, selector: str):  # noqa: ANN001
    if parent is None:
        return None
    return parent.select_one(selector)


def clean_website(raw: Optional[str]) -> Optional[str]:
    """Light cleanup of a website value captured from a listing. Canonicalization
    to a registered domain happens in Phase 2 (transform.canonicalize)."""
    if not raw:
        return None
    raw = raw.strip()
    # Strip common directory redirect wrappers if a bare http(s) url is embedded.
    m = re.search(r"https?://[^\s\"'<>]+", raw)
    return m.group(0) if m else raw or None
