"""Guard: every API path the frontend calls must be proxied by the dev server.

A missing proxy entry is invisible to backend tests — the API works fine when
called directly, but in the browser Vite serves the request itself and returns
404. That is exactly how the ``/synthesize`` endpoint shipped broken.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
SRC = FRONTEND / "src"
VITE_CONFIG = FRONTEND / "vite.config.js"

pytestmark = pytest.mark.skipif(not SRC.is_dir(), reason="frontend not present")


def _fetched_roots() -> set[str]:
    """Top-level path segments the frontend requests (e.g. 'jobs', 'synthesize').

    Matches any absolute-path string literal, not just ``fetch("/...")`` — the
    app routes some calls through a helper (``post("/synthesize", ...)``), and a
    fetch-only regex silently missed exactly the route that broke. Strings that
    name a static file (they carry an extension) are ignored.
    """
    roots: set[str] = set()
    pattern = re.compile(r"""[`'"](/[A-Za-z0-9_${}./-]*)[`'"]""")
    # Both extensions: the API helper lives in a plain .js module, and scanning
    # only .jsx let a whole family of routes (/auth, /library, /learn) slip past.
    sources = [*SRC.rglob("*.jsx"), *SRC.rglob("*.js")]
    for path in sources:
        for match in pattern.finditer(path.read_text()):
            literal = match.group(1)
            first = literal.lstrip("/").split("/")[0]
            if not first or "$" in first:
                continue
            if "." in first:  # a static asset like /logo.svg
                continue
            roots.add(first)
    return roots


def _proxied_roots() -> set[str]:
    text = VITE_CONFIG.read_text()
    match = re.search(r"API_ROUTES\s*=\s*\[([^\]]*)\]", text)
    if match:
        return set(re.findall(r"[\"']([A-Za-z0-9_-]+)[\"']", match.group(1)))
    # Fall back to plain per-path proxy keys ("/jobs": "http://...").
    return set(re.findall(r"[\"']/([A-Za-z0-9_-]+)[\"']\s*:", text))


def test_every_fetched_route_is_proxied():
    fetched = _fetched_roots()
    assert fetched, "no fetch() calls found — did the frontend layout change?"
    missing = fetched - _proxied_roots()
    assert not missing, (
        f"frontend calls {sorted(missing)} but vite.config.js does not proxy "
        f"them; in the browser these 404 instead of reaching the API"
    )


def test_synthesize_is_proxied():
    """Pin the specific route that regressed."""
    assert "synthesize" in _proxied_roots()
