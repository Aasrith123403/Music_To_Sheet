"""Tests for stem separation.

Demucs itself is mocked — running it takes tens of seconds and downloads model
weights. What's tested here is everything around it: validation, the summary
statistics, the job lifecycle, and the download endpoint's path handling.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
import soundfile as sf

from piano_transcribe import stems


def _write_wav(path, seconds=1.0, sr=22050, amplitude=0.3):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    data = (amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sf.write(str(path), data, sr)
    return path


# --- module ------------------------------------------------------------------

def test_models_listed_with_their_stems():
    models = {m["key"]: m for m in stems.list_models()}
    assert set(models) == {"htdemucs", "htdemucs_6s"}
    assert "piano" in models["htdemucs_6s"]["stems"]
    assert "piano" not in models["htdemucs"]["stems"]


def test_missing_file_rejected(tmp_path):
    with pytest.raises(stems.StemError, match="missing"):
        stems.separate(tmp_path / "nope.wav", tmp_path / "out")


def test_unknown_model_rejected(tmp_path):
    src = _write_wav(tmp_path / "a.wav")
    with pytest.raises(stems.StemError, match="Unknown"):
        stems.separate(src, tmp_path / "out", model="not-a-model")


def test_overlong_track_rejected(tmp_path, monkeypatch):
    src = _write_wav(tmp_path / "a.wav")
    monkeypatch.setattr(stems, "MAX_DURATION_S", 0.1)
    with pytest.raises(stems.StemError, match="limit"):
        stems.separate(src, tmp_path / "out")


def test_stem_summary_flags_silence(tmp_path):
    loud = _write_wav(tmp_path / "loud.wav", amplitude=0.5)
    quiet = _write_wav(tmp_path / "quiet.wav", amplitude=0.0)
    assert stems.stem_summary(loud)["silent"] is False
    assert stems.stem_summary(quiet)["silent"] is True
    assert stems.stem_summary(loud)["peak"] > 0.4


# --- API ---------------------------------------------------------------------

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import api.jobs as jobs  # noqa: E402
import api.main as main  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main.db, "DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(main.db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "AUDIO_DIR", tmp_path / "audio")
    (tmp_path / "audio").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(jobs, "STEMS_DIR", tmp_path / "stems")
    with TestClient(main.app) as c:
        yield c


def _wait(client, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get(f"/jobs/{job_id}").json()
        if s["status"] in ("done", "failed", "rejected"):
            return s
        time.sleep(0.05)
    raise AssertionError(f"job did not finish: {s}")


def _fake_separate(monkeypatch, names=("drums", "bass", "piano")):
    """Stand in for demucs: write a real wav per stem so summaries work."""
    def fake(audio_path, out_dir, model=stems.DEFAULT_MODEL, progress=False):
        from pathlib import Path

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for i, name in enumerate(names):
            path = out_dir / f"{name}.wav"
            _write_wav(path, amplitude=0.0 if i == len(names) - 1 else 0.4)
            results.append(stems.StemResult(name=name, path=path, duration_s=1.0))
        return results

    monkeypatch.setattr(jobs, "_run_stems", jobs._run_stems)  # keep runner
    import piano_transcribe.stems as stems_mod
    monkeypatch.setattr(stems_mod, "separate", fake)


def test_separation_job_lifecycle(client, tmp_path, monkeypatch):
    _fake_separate(monkeypatch)
    src = _write_wav(tmp_path / "mix.wav")
    with src.open("rb") as fh:
        r = client.post("/stems", files={"file": ("mix.wav", fh, "audio/wav")},
                        data={"model": "htdemucs_6s"})
    assert r.status_code == 201
    s = _wait(client, r.json()["job_id"])
    assert s["status"] == "done"
    assert s["kind"] == "stems"

    names = [x["name"] for x in s["analysis"]["stems"]]
    assert names == ["drums", "bass", "piano"]
    # The last stem was written silent, and should be flagged rather than hidden.
    assert s["analysis"]["stems"][-1]["silent"] is True

    job_id = s["job_id"]
    assert client.get(f"/jobs/{job_id}/stems/drums").status_code == 200
    assert client.get(f"/jobs/{job_id}/stems/nosuchstem").status_code == 404


def test_stem_name_cannot_escape_the_directory(client, tmp_path, monkeypatch):
    """A crafted stem name must not read arbitrary files."""
    _fake_separate(monkeypatch)
    src = _write_wav(tmp_path / "mix.wav")
    with src.open("rb") as fh:
        r = client.post("/stems", files={"file": ("mix.wav", fh, "audio/wav")})
    job_id = _wait(client, r.json()["job_id"])["job_id"]
    for bad in ("../secret", "..%2Fsecret", "a/b", "a.wav"):
        assert client.get(f"/jobs/{job_id}/stems/{bad}").status_code in (400, 404)


def test_stems_rejects_non_audio(client):
    r = client.post("/stems", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400


def test_stems_rejects_unknown_model(client, tmp_path):
    src = _write_wav(tmp_path / "mix.wav")
    with src.open("rb") as fh:
        r = client.post("/stems", files={"file": ("mix.wav", fh, "audio/wav")},
                        data={"model": "bogus"})
    assert r.status_code == 400
