"""Accounts and sessions.

Deliberately boring and self-contained: SQLite tables, bcrypt password hashes,
and opaque session tokens in an HttpOnly cookie. Server-side sessions (rather
than JWTs) are chosen so that logging out, or revoking a stolen session, is a
row delete rather than a token-expiry wait.

Google sign-in lives in :mod:`api.google_oauth` and reuses
:func:`upsert_google_user` / :func:`create_session` from here.

Scope note: this is sound for a personal/deployed-small app — hashed passwords,
HttpOnly + SameSite cookies, expiring sessions — but it deliberately stops short
of production-grade account management. There is no email verification, no
password reset, and no rate limiting; see the README before exposing it to the
open internet.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass

import bcrypt
from fastapi import Cookie, HTTPException

from . import db

SESSION_COOKIE = "session"
SESSION_TTL_S = 60 * 60 * 24 * 30  # 30 days
MIN_PASSWORD_LEN = 8
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Cookies are marked Secure unless explicitly running plain-HTTP locally.
COOKIE_SECURE = os.environ.get("PIANO_COOKIE_SECURE", "0") == "1"


@dataclass
class User:
    id: int
    email: str
    name: str
    picture: str | None
    has_password: bool

    def public(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
        }


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def init_auth_db() -> None:
    with db._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                name          TEXT NOT NULL,
                picture       TEXT,
                google_sub    TEXT UNIQUE,
                created_at    REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        conn.commit()


# ---------------------------------------------------------------------------
# passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def validate_credentials(email: str, password: str) -> None:
    """Raise a 400 if the email/password obviously won't do."""
    if not _EMAIL_RE.match(email or ""):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters.",
        )


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------

def _row_to_user(row) -> User:
    return User(
        id=row["id"], email=row["email"], name=row["name"],
        picture=row["picture"], has_password=bool(row["password_hash"]),
    )


def create_user(email: str, password: str, name: str | None = None) -> User:
    email = email.strip().lower()
    validate_credentials(email, password)
    now = time.time()
    try:
        with db._connect() as conn:
            cur = conn.execute(
                """INSERT INTO users (email, password_hash, name, created_at)
                   VALUES (?, ?, ?, ?)""",
                (email, hash_password(password), (name or email.split("@")[0]), now),
            )
            conn.commit()
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="That email is already registered.")
    return get_user(user_id)  # type: ignore[return-value]


def get_user(user_id: int) -> User | None:
    with db._connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_email(email: str) -> tuple[User, str | None] | None:
    """Return ``(user, password_hash)`` so callers can verify a password."""
    with db._connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return (_row_to_user(row), row["password_hash"]) if row else None


def authenticate(email: str, password: str) -> User:
    found = get_user_by_email(email)
    # Same message either way: revealing which emails exist is a free gift to
    # anyone enumerating accounts.
    if not found or not verify_password(password, found[1]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return found[0]


def upsert_google_user(sub: str, email: str, name: str, picture: str | None) -> User:
    """Find or create the account behind a Google identity.

    Matching on ``sub`` first (Google's stable id) and falling back to email
    means an existing password account gets *linked* to Google rather than
    duplicated, and a later email change on Google's side doesn't orphan it.
    """
    email = (email or "").strip().lower()
    now = time.time()
    with db._connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
        if row is None and email:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE users SET google_sub = ?, picture = COALESCE(picture, ?) WHERE id = ?",
                    (sub, picture, row["id"]),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
        if row is None:
            cur = conn.execute(
                """INSERT INTO users (email, name, picture, google_sub, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (email or f"{sub}@google.local", name or "Musician", picture, sub, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_user(row)


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now + SESSION_TTL_S),
        )
        conn.commit()
    return token


def delete_session(token: str) -> None:
    with db._connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def user_for_token(token: str | None) -> User | None:
    if not token:
        return None
    with db._connect() as conn:
        row = conn.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token = ? AND s.expires_at > ?""",
            (token, time.time()),
        ).fetchone()
    return _row_to_user(row) if row else None


def purge_expired_sessions() -> None:
    with db._connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
        conn.commit()


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_TTL_S, httponly=True, samesite="lax", secure=COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# --- FastAPI dependencies ----------------------------------------------------

def current_user(session: str | None = Cookie(default=None)) -> User | None:
    """Signed-in user, or ``None`` — anonymous use stays allowed."""
    return user_for_token(session)


def require_user(session: str | None = Cookie(default=None)) -> User:
    """Signed-in user, or a 401 for endpoints that need an account."""
    user = user_for_token(session)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user
