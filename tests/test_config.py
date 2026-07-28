"""Tests for environment loading and the Google config diagnostics.

Pins the failure that produced Google's "invalid_client": a `.env` file that was
never loaded, so `os.environ.get("GOOGLE_CLIENT_ID")` returned nothing.
"""

from __future__ import annotations

import importlib

import pytest

from api import config


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Point the config module at a throwaway .env."""
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.setattr(config, "_loaded", False)
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REDIRECT_URI", "PIANO_APP_URL"):
        monkeypatch.delenv(key, raising=False)
    return path


def test_env_values_reach_the_environment(env_file, monkeypatch):
    env_file.write_text(
        "GOOGLE_CLIENT_ID=123-abc.apps.googleusercontent.com\n"
        "GOOGLE_CLIENT_SECRET=shhh\n"
    )
    assert config.load_env() is True

    import os
    assert os.environ["GOOGLE_CLIENT_ID"] == "123-abc.apps.googleusercontent.com"

    # ...and the OAuth module therefore reports itself configured.
    from api import google_oauth
    assert google_oauth.is_configured() is True


def test_quotes_and_blank_lines_are_tolerated(env_file):
    env_file.write_text(
        '\n# a comment\n'
        'GOOGLE_CLIENT_ID="quoted-id.apps.googleusercontent.com"\n'
        "\nGOOGLE_CLIENT_SECRET='single'\n"
    )
    config.load_env()
    import os
    assert os.environ["GOOGLE_CLIENT_ID"] == "quoted-id.apps.googleusercontent.com"
    assert os.environ["GOOGLE_CLIENT_SECRET"] == "single"


def test_stray_python_lines_do_not_break_parsing(env_file):
    """A .env with pasted Python still yields its real settings.

    This is the exact file that caused the outage: `import os` / `load_dotenv()`
    pasted above the values.
    """
    env_file.write_text(
        "import os\n"
        "from dotenv import load_dotenv\n"
        "load_dotenv()\n"
        "\n"
        "GOOGLE_CLIENT_ID=real-id.apps.googleusercontent.com\n"
        "GOOGLE_CLIENT_SECRET=real-secret\n"
    )
    config.load_env()
    import os
    assert os.environ["GOOGLE_CLIENT_ID"] == "real-id.apps.googleusercontent.com"


def test_missing_env_file_is_not_fatal(env_file):
    assert config.load_env() is False  # file doesn't exist
    assert "disabled" in config.describe()


def test_describe_masks_credentials(env_file):
    secret_id = "888599461234-averylongsecretvalue.apps.googleusercontent.com"
    env_file.write_text(
        f"GOOGLE_CLIENT_ID={secret_id}\nGOOGLE_CLIENT_SECRET=GOCSPX-topsecret\n"
    )
    config.load_env()
    text = config.describe()
    assert "enabled" in text
    assert secret_id not in text            # never log the whole credential
    assert "GOCSPX-topsecret" not in text
    assert "888599" in text                 # but enough to identify it


def test_describe_flags_a_malformed_client_id(env_file):
    """The usual cause of invalid_client: only the numeric prefix was pasted."""
    env_file.write_text(
        "GOOGLE_CLIENT_ID=888599461234\nGOOGLE_CLIENT_SECRET=GOCSPX-x\n"
    )
    config.load_env()
    assert "invalid_client" in config.describe()
