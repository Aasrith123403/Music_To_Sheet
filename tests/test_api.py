"""API tests with the pipeline and YouTube network fully mocked.

These verify the HTTP surface + job lifecycle without touching audio, basic-pitch
or the network, so they run in the light test environment. Skipped entirely if
fastapi/httpx aren't installed.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import api.jobs as jobs
import api.main as main
import api.youtube as youtube
from piano_transcribe.pipeline import PipelineResult, Rejected


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Redirect all data (db + files) to a temp dir so tests are isolated.
    monkeypatch.setattr(main.db, "DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(main.db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(jobs, "MUSICXML_DIR", tmp_path / "musicxml")
    monkeypatch.setattr(jobs, "AUDIO_DIR", tmp_path / "audio")
    with TestClient(main.app) as c:
        yield c


def _wait(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get(f"/jobs/{job_id}").json()
        if s["status"] in ("done", "failed", "rejected"):
            return s
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {s}")


def _fake_pipeline(monkeypatch, *, analysis=None, reject=None):
    def fake(audio_path, out_path, instrument="piano", title="Untitled"):
        if reject:
            raise Rejected(reject)
        from pathlib import Path
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("<score-partwise/>")
        return PipelineResult(events=[], musicxml_path=Path(out_path),
                              analysis=analysis or {"key": "C major", "num_notes": 12},
                              instrument=instrument)
    monkeypatch.setattr(jobs, "run_pipeline", fake)


def test_instruments_endpoint(client):
    data = client.get("/instruments").json()["instruments"]
    assert data[0]["key"] == "piano"
    assert any(i["key"] == "guitar" for i in data)


def test_upload_rejects_bad_type(client):
    r = client.post("/jobs", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400


def test_upload_runs_and_returns_analysis(client, monkeypatch):
    _fake_pipeline(monkeypatch, analysis={"key": "G major", "tempo_bpm": 90})
    r = client.post("/jobs", files={"file": ("t.wav", b"RIFF....", "audio/wav")},
                    data={"instrument": "violin"})
    assert r.status_code == 201
    s = _wait(client, r.json()["job_id"])
    assert s["status"] == "done"
    assert s["instrument"] == "violin"
    assert s["analysis"]["key"] == "G major"
    assert client.get(f"/jobs/{s['job_id']}/musicxml").status_code == 200


def test_upload_rejection_surfaces_reason(client, monkeypatch):
    _fake_pipeline(monkeypatch, reject="Too dense to transcribe.")
    r = client.post("/jobs", files={"file": ("t.wav", b"RIFF....", "audio/wav")})
    s = _wait(client, r.json()["job_id"])
    assert s["status"] == "rejected"
    assert "dense" in s["error"].lower()


def test_youtube_bad_url_400(client):
    assert client.post("/jobs/youtube", json={"url": "https://evil.com/x"}).status_code == 400
    assert client.post("/jobs/youtube", json={"url": ""}).status_code == 400


def test_youtube_flow_uses_title(client, monkeypatch):
    _fake_pipeline(monkeypatch)
    monkeypatch.setattr(jobs.youtube, "probe",
                        lambda url: youtube.VideoInfo(title="My Song", duration_s=30.0))

    def fake_dl(url, out_dir, job_id):
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"{job_id}.wav"
        p.write_bytes(b"RIFF....")
        return p

    monkeypatch.setattr(jobs.youtube, "download_audio", fake_dl)

    r = client.post("/jobs/youtube", json={"url": "https://youtu.be/abc", "instrument": "piano"})
    assert r.status_code == 201
    s = _wait(client, r.json()["job_id"])
    assert s["status"] == "done"
    assert s["filename"] == "My Song"


def test_youtube_rejects_long_video(client, monkeypatch):
    monkeypatch.setattr(jobs.youtube, "probe",
                        lambda url: youtube.VideoInfo(title="Long", duration_s=60 * 30))
    r = client.post("/jobs/youtube", json={"url": "https://youtu.be/abc"})
    s = _wait(client, r.json()["job_id"])
    assert s["status"] == "rejected"
    assert "min" in s["error"].lower()
