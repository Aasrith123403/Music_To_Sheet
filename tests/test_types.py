"""Tests for the NoteEvent interface."""

from __future__ import annotations

import pytest

from piano_transcribe.types import NoteEvent, midi_to_hz


def test_duration_and_frequency():
    e = NoteEvent(pitch=69, onset_s=1.0, offset_s=2.5, velocity=100)
    assert e.duration_s == pytest.approx(1.5)
    assert e.frequency_hz == pytest.approx(440.0)  # A4


def test_offset_before_onset_raises():
    with pytest.raises(ValueError):
        NoteEvent(pitch=60, onset_s=2.0, offset_s=1.0)


def test_midi_to_hz_reference_pitches():
    assert midi_to_hz(69) == pytest.approx(440.0)      # A4
    assert midi_to_hz(60) == pytest.approx(261.6256, abs=1e-3)  # C4
    # An octave up doubles the frequency.
    assert midi_to_hz(81) == pytest.approx(880.0)
