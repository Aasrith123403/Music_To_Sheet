"""Sign in with Google (OAuth 2.0 / OpenID Connect authorization-code flow).

Configured entirely by environment, and **optional**: with no credentials set,
:func:`is_configured` returns False, the API advertises Google as unavailable
and the UI hides the button — the rest of the app is unaffected.

    GOOGLE_CLIENT_ID=...           from Google Cloud Console
    GOOGLE_CLIENT_SECRET=...
    GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

The redirect URI must match the one registered in the Console exactly.

CSRF is handled the standard way: a random ``state`` is stored in a short-lived,
HttpOnly cookie before the redirect and must come back unchanged, so a callback
forged by another site cannot complete a sign-in.
"""

from __future__ import annotations

import os
import secrets

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import auth

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

STATE_COOKIE = "g_state"
STATE_TTL_S = 600

router = APIRouter(prefix="/auth/google", tags=["auth"])


def client_id() -> str | None:
    return os.environ.get("GOOGLE_CLIENT_ID") or None


def client_secret() -> str | None:
    return os.environ.get("GOOGLE_CLIENT_SECRET") or None


def redirect_uri() -> str:
    return os.environ.get(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
    )


def post_login_redirect() -> str:
    """Where to send the browser once sign-in completes (the frontend)."""
    return os.environ.get("PIANO_APP_URL", "http://localhost:5173/")


def is_configured() -> bool:
    return bool(client_id() and client_secret())


@router.get("/login")
def google_login():
    """Kick off the OAuth flow by redirecting to Google's consent screen."""
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail="Google sign-in isn't configured on this server.",
        )
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = str(httpx.URL(AUTH_ENDPOINT, params=params))
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        STATE_COOKIE, state, max_age=STATE_TTL_S, httponly=True,
        samesite="lax", secure=auth.COOKIE_SECURE, path="/",
    )
    return response


@router.get("/callback")
async def google_callback(request: Request, code: str | None = None,
                          state: str | None = None, error: str | None = None):
    """Exchange the authorization code for the user's identity and sign them in."""
    if error:
        raise HTTPException(status_code=400, detail=f"Google sign-in failed: {error}")
    if not is_configured():
        raise HTTPException(status_code=503, detail="Google sign-in isn't configured.")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    expected = request.cookies.get(STATE_COOKIE)
    if not expected or not state or not secrets.compare_digest(state, expected):
        raise HTTPException(status_code=400, detail="Invalid sign-in state; please retry.")

    async with httpx.AsyncClient(timeout=15) as http:
        token_res = await http.post(TOKEN_ENDPOINT, data={
            "code": code,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        })
        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not verify Google sign-in.")
        access_token = token_res.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Google returned no access token.")

        info_res = await http.get(
            USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
        if info_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not read Google profile.")
        info = info_res.json()

    sub = info.get("sub")
    if not sub:
        raise HTTPException(status_code=400, detail="Google profile was incomplete.")

    user = auth.upsert_google_user(
        sub=sub,
        email=info.get("email", ""),
        name=info.get("name") or info.get("given_name") or "Musician",
        picture=info.get("picture"),
    )
    token = auth.create_session(user.id)

    response = RedirectResponse(post_login_redirect(), status_code=302)
    auth.set_session_cookie(response, token)
    response.delete_cookie(STATE_COOKIE, path="/")
    return response
