"""Tests for the eval harness.

The load-bearing one is ``test_self_scoring_is_perfect``: scoring ground truth
against itself must return F1 = 1.0. If that ever breaks, no other eval number
can be trusted.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from piano_transcribe.evaluate import (
    evaluate_transcription,
    note_events_to_mireval,
)
from piano_transcribe.types import NoteEvent, midi_to_hz


def test_self_scoring_is_perfect(c_major_scale):
    """Reference scored against an identical estimate -> F1 == 1.0 everywhere."""
    m = evaluate_transcription(c_major_scale, c_major_scale)
    assert m.onset_f1 == pytest.approx(1.0)
    assert m.onset_precision == pytest.approx(1.0)
    assert m.onset_recall == pytest.approx(1.0)
    assert m.onset_offset_f1 == pytest.approx(1.0)
    assert m.n_reference == m.n_estimate == len(c_major_scale)


def test_empty_estimate_is_zero(c_major_scale):
    """No estimated notes -> zero recall and F1, but the call must not crash."""
    m = evaluate_transcription(c_major_scale, [])
    assert m.onset_f1 == pytest.approx(0.0)
    assert m.onset_recall == pytest.approx(0.0)
    assert m.n_estimate == 0


def test_missing_one_note_lowers_f1(c_major_scale):
    """Dropping a note keeps precision at 1.0 but pushes recall/F1 below 1."""
    estimate = c_major_scale[:-1]  # drop the last note
    m = evaluate_transcription(c_major_scale, estimate)
    assert m.onset_precision == pytest.approx(1.0)
    assert m.onset_recall < 1.0
    assert m.onset_f1 < 1.0
    # F1 = 2PR/(P+R) with P=1, R=7/8 -> 14/15.
    assert m.onset_f1 == pytest.approx(14 / 15)


def test_onset_within_tolerance_still_matches(c_major_scale):
    """A 20 ms onset shift (< 50 ms tolerance) is still a match."""
    shifted = [
        NoteEvent(e.pitch, e.onset_s + 0.02, e.offset_s + 0.02, e.velocity)
        for e in c_major_scale
    ]
    m = evaluate_transcription(c_major_scale, shifted)
    assert m.onset_f1 == pytest.approx(1.0)


def test_wrong_pitch_does_not_match(c_major_scale):
    """A semitone-off estimate matches nothing (pitch tolerance is a quarter-tone)."""
    wrong = [
        NoteEvent(e.pitch + 1, e.onset_s, e.offset_s, e.velocity)
        for e in c_major_scale
    ]
    m = evaluate_transcription(c_major_scale, wrong)
    assert m.onset_f1 == pytest.approx(0.0)


def test_note_events_to_mireval_shapes(c_major_scale):
    intervals, pitches = note_events_to_mireval(c_major_scale)
    assert intervals.shape == (len(c_major_scale), 2)
    assert pitches.shape == (len(c_major_scale),)
    # First note is C4 (MIDI 60).
    assert pitches[0] == pytest.approx(midi_to_hz(60))
    assert np.all(intervals[:, 1] >= intervals[:, 0])


def test_note_events_to_mireval_empty():
    intervals, pitches = note_events_to_mireval([])
    assert intervals.shape == (0, 2)
    assert pitches.shape == (0,)
