"""Tests for the sheet-music -> MIDI synthesis path (structured formats)."""

from __future__ import annotations

import shutil
import time

import pytest

from piano_transcribe import importscore, synthesize


def _write_sample(path):
    """A tiny 2-bar score (melody + a chord) written to MusicXML."""
    from music21 import chord, meter, note, stream, tempo

    s = stream.Score()
    p = stream.Part()
    p.insert(0, tempo.MetronomeMark(number=120))
    p.insert(0, meter.TimeSignature("4/4"))
    p.append(note.Note("C4", quarterLength=1))
    p.append(note.Note("E4", quarterLength=1))
    p.append(chord.Chord(["G4", "C5", "E5"], quarterLength=2))
    s.insert(0, p)
    s.write("musicxml", fp=str(path))
    return path


def test_score_to_events_expands_chords(tmp_path):
    from music21 import converter

    score = converter.parse(str(_write_sample(tmp_path / "s.musicxml")))
    events = synthesize.score_to_events(score)
    # 2 single notes + a 3-note chord = 5 events.
    assert len(events) == 5
    assert events[0].onset_s == pytest.approx(0.0)
    # Chord starts at beat 3 -> 1.0 s at 120 bpm... 2 quarters = 1.0s.
    assert max(e.offset_s for e in events) == pytest.approx(2.0)


def test_synthesize_sets_instrument_program(tmp_path):
    import pretty_midi

    src = _write_sample(tmp_path / "in.musicxml")
    res = synthesize.synthesize(src, tmp_path / "o.mid", tmp_path / "o.musicxml",
                                instrument_key="flute")
    assert res["midi_path"].exists() and res["musicxml_path"].exists()
    progs = [i.program for i in pretty_midi.PrettyMIDI(str(res["midi_path"])).instruments
             if not i.is_drum]
    assert progs == [73]  # flute
    assert res["analysis"]["num_notes"] == 5
    assert res["analysis"]["instrument"] == "Flute"


def test_midi_input_roundtrips(tmp_path):
    from music21 import converter

    # MusicXML -> MIDI, then synthesize *from* that MIDI.
    score = converter.parse(str(_write_sample(tmp_path / "s.musicxml")))
    midi_in = tmp_path / "in.mid"
    score.write("midi", fp=str(midi_in))
    res = synthesize.synthesize(midi_in, tmp_path / "o.mid", tmp_path / "o.xml",
                                instrument_key="trumpet")
    import pretty_midi
    progs = [i.program for i in pretty_midi.PrettyMIDI(str(res["midi_path"])).instruments
             if not i.is_drum]
    assert progs == [56]  # trumpet


def test_unsupported_format_raises(tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("hi")
    with pytest.raises(importscore.ScoreImportError):
        importscore.load_score(bad)


@pytest.mark.skipif(shutil.which("fluidsynth") is None, reason="fluidsynth not installed")
def test_offline_wav_render(tmp_path):
    src = _write_sample(tmp_path / "in.musicxml")
    res = synthesize.synthesize(src, tmp_path / "o.mid", tmp_path / "o.xml", "piano")
    wav = synthesize.midi_to_wav(res["midi_path"], tmp_path / "o.wav")
    assert wav is not None and wav.exists()
    assert wav.stat().st_size > 1000  # real audio, not an empty file


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
    monkeypatch.setattr(main, "SHEET_DIR", tmp_path / "sheets")
    monkeypatch.setattr(jobs, "MUSICXML_DIR", tmp_path / "musicxml")
    monkeypatch.setattr(jobs, "MIDI_DIR", tmp_path / "midi")
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


def test_synthesize_endpoint(client, tmp_path):
    src = _write_sample(tmp_path / "up.musicxml")
    with src.open("rb") as fh:
        r = client.post("/synthesize", files={"file": ("up.musicxml", fh, "application/xml")},
                        data={"instrument": "guitar"})
    assert r.status_code == 201
    s = _wait(client, r.json()["job_id"])
    assert s["status"] == "done"
    assert s["kind"] == "synthesize"
    assert s["midi_ready"] and s["musicxml_ready"]
    assert s["analysis"]["instrument"] == "Guitar"
    assert client.get(f"/jobs/{s['job_id']}/midi").status_code == 200
    assert client.get(f"/jobs/{s['job_id']}/musicxml").status_code == 200


def test_synthesize_rejects_bad_type(client):
    r = client.post("/synthesize", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400
