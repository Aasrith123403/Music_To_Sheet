"""Baseline pipeline tests that don't need audio.

These build a synthetic :class:`BeatGrid` directly so quantize -> voices ->
spelling -> notate can be exercised end to end without running beat tracking
(which needs an audio file). ``beats.track_beats`` itself is covered by
``test_beats.py`` when librosa is installed.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from piano_transcribe import notate, quantize, spelling, voices
from piano_transcribe.beats import seconds_to_beats
from piano_transcribe.types import BeatGrid, NoteEvent


@pytest.fixture
def half_second_grid() -> BeatGrid:
    """16 beats at a steady 120 BPM (0.5 s/beat), 4/4."""
    beats = [i * 0.5 for i in range(16)]
    return BeatGrid(beat_times_s=beats, downbeats_s=beats[::4],
                    beats_per_bar=4, beat_unit=4)


def test_seconds_to_beats_interpolates(half_second_grid):
    # Beat 0 at 0.0 s, one beat every 0.5 s.
    pos = seconds_to_beats(half_second_grid, [0.0, 0.5, 0.75, 2.0])
    assert pos[0] == pytest.approx(0.0)
    assert pos[1] == pytest.approx(1.0)
    assert pos[2] == pytest.approx(1.5)   # halfway between beats 1 and 2
    assert pos[3] == pytest.approx(4.0)


def test_seconds_to_beats_extrapolates(half_second_grid):
    # Before the first beat and after the last, using edge spacing.
    pos = seconds_to_beats(half_second_grid, [-0.5, 8.0])  # last beat is 7.5s
    assert pos[0] == pytest.approx(-1.0)
    assert pos[1] == pytest.approx(16.0)


def test_quantize_snaps_scale(c_major_scale, half_second_grid):
    quantized = quantize.quantize_nearest(c_major_scale, half_second_grid)
    assert len(quantized) == len(c_major_scale)
    # Quarter notes at 0.5 s on a 0.5 s/beat grid -> 1 beat each, onsets 0,1,2...
    assert quantized[0].onset_beats == Fraction(0)
    assert quantized[1].onset_beats == Fraction(1)
    assert all(q.duration_beats == Fraction(1) for q in quantized)


def test_quantize_shifts_to_zero(half_second_grid):
    # A note that starts at beat 2 should be shifted so the piece begins at 0.
    events = [NoteEvent(64, 1.0, 1.5), NoteEvent(67, 1.5, 2.0)]
    quantized = quantize.quantize_nearest(events, half_second_grid)
    assert quantized[0].onset_beats == Fraction(0)
    assert quantized[1].onset_beats == Fraction(1)


def test_voice_split_at_middle_c():
    events = [NoteEvent(72, 0.0, 0.5), NoteEvent(48, 0.0, 0.5), NoteEvent(60, 0.0, 0.5)]
    grid = BeatGrid(beat_times_s=[0.0, 0.5, 1.0], beats_per_bar=4)
    quantized = quantize.quantize_nearest(events, grid)
    voices.assign_middle_c_split(quantized)
    by_pitch = {q.event.pitch: q for q in quantized}
    assert by_pitch[72].staff == 1  # above middle C -> treble
    assert by_pitch[60].staff == 1  # middle C -> treble
    assert by_pitch[48].staff == 2  # below -> bass


def test_estimate_key_c_major(c_major_scale):
    key = spelling.estimate_key(c_major_scale)
    # A pure C-major scale is diatonically ambiguous with its relative A minor;
    # accept either, and either way the signature has no accidentals.
    assert (key.tonic_pc, key.mode) in {(0, "major"), (9, "minor")}
    assert key.key_signature_sharps == 0


def test_key_signature_sharps_known_keys():
    assert spelling.KeyEstimate(7, "major", 1.0).key_signature_sharps == 1   # G
    assert spelling.KeyEstimate(5, "major", 1.0).key_signature_sharps == -1  # F
    assert spelling.KeyEstimate(10, "major", 1.0).key_signature_sharps == -2  # Bb
    assert spelling.KeyEstimate(9, "minor", 1.0).key_signature_sharps == 0   # a minor


def test_spelling_flat_key_uses_flats():
    key = spelling.KeyEstimate(5, "major", 1.0)  # F major -> flats
    assert key.uses_flats
    events = [NoteEvent(70, 0.0, 0.5)]  # Bb4
    assert spelling.spell_notes(events, key) == ["B-4"]


def test_full_notation_writes_musicxml(c_major_scale, half_second_grid, tmp_path):
    quantized = quantize.quantize_nearest(c_major_scale, half_second_grid)
    voices.assign_middle_c_split(quantized)
    key = spelling.estimate_key(c_major_scale)
    names = spelling.spell_notes(c_major_scale, key)

    score = notate.build_score(quantized, half_second_grid, key,
                               note_names=names, title="C Major Scale")
    out = notate.export_musicxml(score, tmp_path / "scale.musicxml")

    assert out.exists()
    text = out.read_text()
    assert "score-partwise" in text
    # Two staves worth of notes accounted for.
    assert text.count("<note") >= len(c_major_scale)
