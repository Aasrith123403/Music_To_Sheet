"""Tests for OMR engine selection/dispatch in importscore.

These mock the engines, so they run without Audiveris or oemer installed.
"""

from __future__ import annotations

import pytest

from piano_transcribe import importscore


def _tiny_musicxml(path):
    from music21 import note, stream

    s = stream.Stream()
    s.append(note.Note("C4"))
    s.write("musicxml", fp=str(path))
    return path


def test_audiveris_cmd_from_jar_env(monkeypatch, tmp_path):
    jar = tmp_path / "audiveris.jar"
    jar.write_bytes(b"x")
    monkeypatch.delenv("AUDIVERIS_CMD", raising=False)
    monkeypatch.setenv("AUDIVERIS_JAR", str(jar))
    assert importscore._audiveris_cmd() == ["java", "-jar", str(jar)]


def test_audiveris_cmd_prefers_explicit_cmd(monkeypatch):
    monkeypatch.setenv("AUDIVERIS_CMD", "/opt/audiveris/bin/Audiveris")
    assert importscore._audiveris_cmd() == ["/opt/audiveris/bin/Audiveris"]


def test_forced_audiveris_without_launcher_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("PIANO_OMR_ENGINE", "audiveris")
    monkeypatch.setattr(importscore, "_audiveris_cmd", lambda: None)
    img = tmp_path / "scan.png"
    img.write_bytes(b"x")
    with pytest.raises(importscore.ScoreImportError, match="[Aa]udiveris"):
        importscore.load_score(img)


def test_auto_prefers_audiveris(monkeypatch, tmp_path):
    """When a launcher is present, 'auto' uses Audiveris (not oemer)."""
    monkeypatch.setenv("PIANO_OMR_ENGINE", "auto")
    monkeypatch.setattr(importscore, "_audiveris_cmd", lambda: ["audiveris"])
    mxl = _tiny_musicxml(tmp_path / "out.musicxml")
    used = {}
    monkeypatch.setattr(importscore, "_run_audiveris", lambda p: (used.setdefault("audiveris", True), mxl)[1])

    def _oemer_should_not_run(p):
        raise AssertionError("oemer should not be called when Audiveris is available")

    monkeypatch.setattr(importscore, "_run_oemer", _oemer_should_not_run)

    img = tmp_path / "scan.png"
    img.write_bytes(b"x")
    score = importscore.load_score(img)
    assert used.get("audiveris") is True
    assert len(score.recurse().notes) == 1


def test_auto_falls_back_to_oemer(monkeypatch, tmp_path):
    """No Audiveris launcher -> 'auto' falls back to oemer."""
    monkeypatch.setenv("PIANO_OMR_ENGINE", "auto")
    monkeypatch.setattr(importscore, "_audiveris_cmd", lambda: None)
    mxl = _tiny_musicxml(tmp_path / "out.musicxml")
    monkeypatch.setattr(importscore, "_run_oemer", lambda p: mxl)

    img = tmp_path / "scan.png"
    img.write_bytes(b"x")
    score = importscore.load_score(img)
    assert len(score.recurse().notes) == 1
