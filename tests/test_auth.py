"""Tests for accounts, sessions, library ownership, and the learning endpoints."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import api.auth as auth  # noqa: E402
import api.jobs as jobs  # noqa: E402
import api.main as main  # noqa: E402

GOOD_PW = "correct horse battery"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main.db, "DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(main.db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(main, "SHEET_DIR", tmp_path / "sheets")
    monkeypatch.setattr(jobs, "MUSICXML_DIR", tmp_path / "musicxml")
    monkeypatch.setattr(jobs, "MIDI_DIR", tmp_path / "midi")
    with TestClient(main.app) as c:
        yield c


def _register(client, email="a@example.com", password=GOOD_PW, name="Tester"):
    return client.post("/auth/register",
                       json={"email": email, "password": password, "name": name})


# --- passwords ---------------------------------------------------------------

def test_password_hash_roundtrip():
    hashed = auth.hash_password("s3cret-passphrase")
    assert hashed != "s3cret-passphrase"          # never stored in the clear
    assert auth.verify_password("s3cret-passphrase", hashed)
    assert not auth.verify_password("wrong", hashed)
    assert not auth.verify_password("anything", None)


def test_hashes_are_salted():
    """Two accounts with the same password must not share a hash."""
    assert auth.hash_password(GOOD_PW) != auth.hash_password(GOOD_PW)


# --- registration / login ----------------------------------------------------

def test_register_then_me(client):
    r = _register(client)
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "a@example.com"
    me = client.get("/auth/me").json()
    assert me["user"]["name"] == "Tester"
    # Whether Google is available depends on the developer's own credentials,
    # so assert the shape, not the value — see test_google_enabled_* below.
    assert isinstance(me["google_enabled"], bool)


def test_google_enabled_false_without_credentials(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert client.get("/auth/me").json()["google_enabled"] is False


def test_google_enabled_true_with_credentials(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    assert client.get("/auth/me").json()["google_enabled"] is True


@pytest.mark.parametrize("email,password,code", [
    ("a@example.com", "short", 400),      # too short
    ("not-an-email", GOOD_PW, 400),       # malformed
])
def test_registration_validation(client, email, password, code):
    assert client.post("/auth/register",
                       json={"email": email, "password": password}).status_code == code


def test_duplicate_email_rejected(client):
    _register(client)
    assert _register(client).status_code == 409


def test_login_logout_cycle(client):
    _register(client)
    client.post("/auth/logout")
    assert client.get("/auth/me").json()["user"] is None
    assert client.post("/auth/login",
                       json={"email": "a@example.com", "password": "nope-nope-nope"}
                       ).status_code == 401
    assert client.post("/auth/login",
                       json={"email": "a@example.com", "password": GOOD_PW}
                       ).status_code == 200
    assert client.get("/auth/me").json()["user"]["email"] == "a@example.com"


def test_login_does_not_reveal_whether_email_exists(client):
    """Unknown email and wrong password must be indistinguishable."""
    _register(client)
    client.post("/auth/logout")
    unknown = client.post("/auth/login", json={"email": "ghost@example.com", "password": GOOD_PW})
    wrong = client.post("/auth/login", json={"email": "a@example.com", "password": "bad-password"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_session_is_revoked_server_side(client):
    """Logging out invalidates the token even if the cookie is replayed."""
    _register(client)
    token = client.cookies.get(auth.SESSION_COOKIE)
    assert auth.user_for_token(token) is not None
    client.post("/auth/logout")
    assert auth.user_for_token(token) is None


# --- library / ownership -----------------------------------------------------

def _make_job(client, user_id, job_id="job1", title=None):
    main.db.create_job(job_id, filename="piece.wav", audio_path=None,
                       user_id=user_id, title=title)
    main.db.update_job(job_id, status=main.db.STATUS_DONE,
                       analysis='{"key": "C major", "num_notes": 10}')


def test_library_requires_sign_in(client):
    assert client.get("/library").status_code == 401


def test_library_lists_only_own_work(client):
    _register(client, email="one@example.com")
    mine = client.get("/auth/me").json()["user"]["id"]
    _make_job(client, mine, "mine", title="My Piece")
    _make_job(client, mine + 999, "theirs", title="Someone Else")

    items = client.get("/library").json()["items"]
    assert [i["job_id"] for i in items] == ["mine"]
    assert items[0]["title"] == "My Piece"


def test_other_users_job_is_not_readable(client):
    _register(client, email="one@example.com")
    mine = client.get("/auth/me").json()["user"]["id"]
    _make_job(client, mine + 999, "theirs")
    # 404 rather than 403: don't confirm the id exists.
    assert client.get("/jobs/theirs").status_code == 404
    assert client.delete("/jobs/theirs").status_code == 404


def test_anonymous_job_stays_reachable(client):
    """A job created signed-out isn't lost — it just isn't in a library."""
    _make_job(client, None, "anon")
    assert client.get("/jobs/anon").status_code == 200
    assert client.get("/jobs/anon").json()["saved"] is False


def test_rename_and_delete(client):
    _register(client)
    mine = client.get("/auth/me").json()["user"]["id"]
    _make_job(client, mine, "j1", title="Old")

    assert client.patch("/jobs/j1", json={"title": "New Name"}).status_code == 200
    assert client.get("/jobs/j1").json()["title"] == "New Name"
    assert client.patch("/jobs/j1", json={"title": "  "}).status_code == 400

    assert client.delete("/jobs/j1").status_code == 200
    assert client.get("/jobs/j1").status_code == 404
    assert client.get("/library").json()["total"] == 0


def test_job_gets_difficulty_rating(client):
    _register(client)
    mine = client.get("/auth/me").json()["user"]["id"]
    _make_job(client, mine, "j2")
    body = client.get("/jobs/j2").json()
    assert body["analysis"]["difficulty"]["level"] in range(1, 6)


# --- learning ----------------------------------------------------------------

def test_quiz_cards_are_engraved_and_answerable(client):
    cards = client.get("/learn/quiz?clef=treble&count=5").json()["cards"]
    assert len(cards) == 5
    for card in cards:
        assert "score-partwise" in card["musicxml"]
        assert card["answer"] in card["options"]
        assert len(card["options"]) == 4


def test_quiz_clef_is_validated(client):
    assert client.get("/learn/quiz?clef=alto").status_code == 400


def test_keys_reference(client):
    keys = client.get("/learn/keys").json()["keys"]
    assert len(keys) == 13
    assert any(k["major"].startswith("C major") for k in keys)
