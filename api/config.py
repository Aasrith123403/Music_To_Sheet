"""Environment configuration.

Importing this module loads ``.env`` from the project root into the process
environment, so every ``os.environ.get(...)`` elsewhere just works. Import it
before anything that reads configuration.

``.env`` is data, not code: plain ``KEY=value`` lines, never executed. If you
find Python statements in it (``import os``, ``load_dotenv()``), they belong in
this module instead — in the file they are silently ignored, which looks exactly
like credentials that "don't work".

Real environment variables win over ``.env`` (the python-dotenv default), which
is what you want in a deployment — but it also means a stale ``export`` in the
shell running the server will quietly override the file. :func:`describe` exists
to make that visible.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

_loaded = False


def load_env(override: bool = False) -> bool:
    """Load ``.env`` into ``os.environ``. Returns whether the file was found."""
    global _loaded
    if _loaded:
        return ENV_FILE.exists()
    _loaded = True
    if not ENV_FILE.exists():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:  # keep the app usable without the optional dependency
        return _load_env_fallback(override)
    load_dotenv(ENV_FILE, override=override)
    return True


def _load_env_fallback(override: bool) -> bool:
    """Minimal KEY=value parser, for when python-dotenv isn't installed."""
    for raw in ENV_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key.replace("_", "").isalnum():
            continue
        if override or key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")
    return True


def _mask(value: str | None) -> str:
    """Show enough of a credential to identify it, never enough to use it."""
    if not value:
        return "(unset)"
    if len(value) <= 12:
        return "…" * 3
    return f"{value[:8]}…{value[-8:]}"


def describe() -> str:
    """One-line summary of the Google config, safe to print to a log."""
    client = os.environ.get("GOOGLE_CLIENT_ID")
    secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client or not secret:
        missing = [
            name for name, val in
            (("GOOGLE_CLIENT_ID", client), ("GOOGLE_CLIENT_SECRET", secret))
            if not val
        ]
        found = "found" if ENV_FILE.exists() else "not found"
        return (f"Google sign-in: disabled (missing {', '.join(missing)}; "
                f".env {found} at {ENV_FILE})")

    warning = ""
    if not client.endswith(".apps.googleusercontent.com"):
        # The single most common cause of Google's "invalid_client" error.
        warning = ("  ⚠ client id does not end in .apps.googleusercontent.com "
                   "— Google will reject it as invalid_client")
    return (
        f"Google sign-in: enabled\n"
        f"  client id    : {_mask(client)}\n"
        f"  redirect uri : {os.environ.get('GOOGLE_REDIRECT_URI', '(default)')}\n"
        f"  after login  : {os.environ.get('PIANO_APP_URL', '(default)')}"
        + (f"\n{warning}" if warning else "")
    )


# Load on import so simply importing api.* picks the configuration up.
load_env()
