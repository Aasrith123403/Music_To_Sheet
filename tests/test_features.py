"""Tests for instrument support, analysis, and the transcribability gate."""

from __future__ import annotations

import pytest

from piano_transcribe import analyze as analyze_mod
from piano_transcribe import instruments, notate, quality, quantize, spelling, voices
from piano_transcribe.types import BeatGrid, NoteEvent


@pytest.fixture
def steady_grid() -> BeatGrid:
    beats = [i * 0.5 for i in range(16)]
    return BeatGrid(beat_times_s=beats, downbeats_s=beats[::4], beats_per_bar=4, beat_unit=4)


# --- instrument registry ----------------------------------------------------

def test_get_instrument_fallback():
    assert instruments.get_instrument(None).key == "piano"
    assert instruments.get_instrument("nonsense").key == "piano"
    assert instruments.get_instrument("cello").clef == "bass"


def test_list_instruments_has_piano_first():
    listed = instruments.list_instruments()
    assert listed[0]["key"] == "piano"
    keys = {i["key"] for i in listed}
    assert {"guitar", "violin", "flute", "alto_sax"} <= keys


def test_transposing_instrument_spec():
    clar = instruments.get_instrument("clarinet")
    assert clar.transposition == 2  # written a whole step above sounding
    assert clar.notation == "single"


# --- notation: single staff vs grand ---------------------------------------

def test_single_staff_instrument_one_part(steady_grid, c_major_scale):
    q = quantize.quantize_nearest(c_major_scale, steady_grid)
    for x in q:
        x.staff, x.voice = 1, 1
    key = spelling.estimate_key(c_major_scale)
    names = spelling.spell_notes(c_major_scale, key)
    score = notate.build_score(q, steady_grid, key, note_names=names,
                               instrument="flute", title="Flute")
    parts = list(score.parts)
    assert len(parts) == 1  # single staff, not a grand staff
    xml = notate.export_musicxml(score, "/tmp/_flute_test.musicxml").read_text()
    assert "<sign>G</sign>" in xml  # treble clef


def test_piano_still_grand_staff(steady_grid, c_major_scale):
    q = quantize.quantize_nearest(c_major_scale, steady_grid)
    voices.assign_middle_c_split(q)
    key = spelling.estimate_key(c_major_scale)
    score = notate.build_score(q, steady_grid, key, instrument="piano")
    assert len(list(score.parts)) == 2


def test_simultaneous_notes_become_chords(steady_grid, tmp_path):
    # Left-hand block chords (C2-E2-G2) on beats 0 and 2, plus a RH melody.
    events = []
    for onset in (0.0, 1.0):
        for p in (36, 40, 43):
            events.append(NoteEvent(p, onset, onset + 0.9, 60))
    for i, p in enumerate([72, 74, 76, 77]):
        events.append(NoteEvent(p, i * 0.5, i * 0.5 + 0.4, 80))
    events.sort(key=lambda e: (e.onset_s, e.pitch))

    q = quantize.quantize_nearest(events, steady_grid)
    voices.assign_middle_c_split(q)  # chord -> bass, melody -> treble
    key = spelling.estimate_key(events)
    names = spelling.spell_notes(events, key)
    score = notate.build_score(q, steady_grid, key, note_names=names)

    xml = notate.export_musicxml(score, tmp_path / "chords.musicxml").read_text()
    # MusicXML marks 2nd+ chord members with <chord/>. Two 3-note chords -> >=4.
    assert xml.count("<chord") >= 4

    # In the object model, the bass staff should contain Chord objects.
    from music21 import chord as m21chord
    bass = list(score.parts)[1]
    assert any(isinstance(el, m21chord.Chord) for el in bass.recurse().notes)


# --- analysis ---------------------------------------------------------------

def test_analyze_reports_expected_fields(steady_grid, c_major_scale):
    key = spelling.estimate_key(c_major_scale)
    info = analyze_mod.analyze(c_major_scale, steady_grid, key, duration_s=4.0)
    assert info["num_notes"] == len(c_major_scale)
    assert info["duration_s"] == 4.0
    assert info["duration_hms"] == "0:04"
    assert info["tempo_bpm"] == pytest.approx(120.0)  # 0.5 s/beat
    assert info["texture"] == "monophonic"  # scale is sequential
    assert info["pitch_range"]["low"] == "C4"
    assert info["pitch_range"]["high"] == "C5"
    assert info["time_signature"] == "4/4"
    assert len(info["scale"]) == 7


def test_analyze_detects_polyphony():
    # Two notes fully overlapping -> polyphonic.
    events = [NoteEvent(60, 0.0, 1.0), NoteEvent(64, 0.0, 1.0)]
    grid = BeatGrid(beat_times_s=[0.0, 0.5, 1.0], beats_per_bar=4)
    key = spelling.estimate_key(events)
    info = analyze_mod.analyze(events, grid, key, duration_s=1.0)
    assert info["texture"] == "polyphonic"
    assert info["max_polyphony"] == 2


# --- transcribability gate --------------------------------------------------

def test_gate_rejects_too_few_notes():
    v = quality.assess_transcription([NoteEvent(60, 0, 0.5)], duration_s=30)
    assert not v.ok and "few" in v.reason.lower()


def test_gate_rejects_too_long():
    v = quality.assess_transcription([NoteEvent(60, 0, 0.5)] * 50, duration_s=60 * 20)
    assert not v.ok and "min" in v.reason.lower()


def test_gate_rejects_dense_mix():
    # 20 notes all sounding at once.
    events = [NoteEvent(40 + i, 0.0, 2.0) for i in range(20)]
    v = quality.assess_transcription(events, duration_s=10)
    assert not v.ok and "dense" in v.reason.lower()


def test_gate_accepts_normal_solo():
    events = [NoteEvent(60 + (i % 12), i * 0.4, i * 0.4 + 0.4) for i in range(30)]
    v = quality.assess_transcription(events, duration_s=15)
    assert v.ok
