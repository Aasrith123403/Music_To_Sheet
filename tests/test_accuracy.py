"""Regression tests for the accuracy fixes.

Each test pins a specific bug that was found by measurement (see
``cli/bench_quantize.py``), so a future change that reintroduces it fails here
rather than silently degrading transcriptions.
"""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

from cli.bench_quantize import CORPUS, perfect_grid, score, to_events
from piano_transcribe import cleanup, quantize
from piano_transcribe.beats import grid_from_onsets
from piano_transcribe.types import BeatGrid, NoteEvent

F = Fraction


# --- quantizer ---------------------------------------------------------------

def _grid(bpm=100.0, n=40):
    spb = 60.0 / bpm
    beats = [i * spb for i in range(n)]
    return BeatGrid(beat_times_s=beats, downbeats_s=beats[::4], beats_per_bar=4)


def test_offsets_in_empty_beats_keep_their_duration():
    """A note held through a beat containing no onsets keeps its notated value.

    Regression: the fallback subdivision for an event-free beat was a whole
    quarter, so such durations were rounded to whole beats.
    """
    grid = _grid()
    spb = 0.6
    # Onset on beat 0, offset at beat 2.5 — beats 1 and 2 hold no onsets.
    events = [NoteEvent(60, 0.0, 2.5 * spb, 80), NoteEvent(72, 0.0, 0.5 * spb, 80)]
    q = quantize.quantize_cost(events, grid)
    assert q[0].duration_beats == F(5, 2)


def test_dense_beats_do_not_collapse_to_quarters():
    """Four sixteenths in one beat stay sixteenths.

    Regression: complexity was multiplied by the note count, so busy beats were
    pushed onto the coarsest grid and every offbeat note lost its position.
    """
    grid = _grid()
    spb = 0.6
    events = [NoteEvent(60 + i, i * 0.25 * spb, (i * 0.25 + 0.25) * spb, 80)
              for i in range(4)]
    q = quantize.quantize_cost(events, grid)
    assert [x.onset_beats for x in q] == [F(0), F(1, 4), F(1, 2), F(3, 4)]
    assert all(x.duration_beats == F(1, 4) for x in q)


@pytest.mark.parametrize("piece", ["eighths", "dotted", "syncopation", "mixed"])
def test_bench_pieces_are_near_perfect(piece):
    """The quantizer reproduces known rhythms on a clean grid."""
    truth = CORPUS[piece]
    events, ordered = to_events(truth, 100.0, 0.012, random.Random(3))
    q = quantize.quantize_cost(events, perfect_grid(truth, 100.0))
    onset_acc, dur_acc = score(ordered, q)
    assert onset_acc >= 0.95
    assert dur_acc >= 0.95


# --- beat tracking -----------------------------------------------------------

def test_even_eighths_do_not_double_the_tempo():
    """A stream of even eighths must not be read as beats at twice the tempo.

    Regression: an even subdivision has no energy at the beat period, so a
    plain phase-locked estimate locked onto the eighth-note pulse.
    """
    bpm = 100.0
    spb = 60.0 / bpm
    onsets = [i * 0.5 * spb for i in range(24)]
    grid = grid_from_onsets(onsets, bpm_hint=bpm)
    period = grid.beat_times_s[1] - grid.beat_times_s[0]
    assert 60.0 / period == pytest.approx(bpm, rel=0.06)


def test_half_tempo_hint_is_corrected():
    """An octave-wrong tempo hint is overridden, not inherited."""
    bpm = 96.0
    spb = 60.0 / bpm
    onsets = [i * spb for i in range(16)]
    grid = grid_from_onsets(onsets, bpm_hint=bpm / 2)  # beat tracker halved it
    period = grid.beat_times_s[1] - grid.beat_times_s[0]
    assert 60.0 / period == pytest.approx(bpm, rel=0.06)


# --- cleanup -----------------------------------------------------------------

def test_repeated_notes_are_not_merged():
    """Contiguous repeats of one pitch stay separate notes.

    Regression: gap-only merging fused a repeated bass note into one long note,
    destroying recall.
    """
    events = [NoteEvent(48, 0.0, 1.0, 80), NoteEvent(48, 1.0, 2.0, 80),
              NoteEvent(48, 2.0, 3.0, 80)]
    assert len(cleanup.merge_split_notes(events)) == 3


def test_short_fragment_is_absorbed():
    """A tiny same-pitch speck right after a note is absorbed into it."""
    events = [NoteEvent(60, 0.0, 1.0, 80), NoteEvent(60, 1.01, 1.05, 40)]
    merged = cleanup.merge_split_notes(events)
    assert len(merged) == 1
    assert merged[0].offset_s == pytest.approx(1.05)


def test_harmonic_ghost_removed_but_real_octave_kept():
    """A quiet octave-up artifact goes; a real doubled octave stays."""
    loud = NoteEvent(48, 0.0, 1.0, 100)
    ghost = NoteEvent(60, 0.0, 0.8, 30)      # quiet, contained -> artifact
    real = NoteEvent(60, 0.0, 1.0, 95)       # comparable velocity -> genuine
    assert cleanup.drop_harmonic_ghosts([loud, ghost]) == [loud]
    assert len(cleanup.drop_harmonic_ghosts([loud, real])) == 2


def test_clean_events_preserves_a_clean_performance():
    """Cleanup must not delete notes from already-clean input."""
    events = [NoteEvent(60 + (i % 5), i * 0.5, i * 0.5 + 0.45, 80) for i in range(20)]
    assert len(cleanup.clean_events(events)) == len(events)


# --- notation fidelity (ground-truth-free validity check) --------------------

def test_fidelity_is_perfect_on_exact_timing():
    """Notes played exactly on the grid are notated exactly where they fall."""
    from piano_transcribe.evaluate import notation_fidelity

    grid = _grid()
    spb = 0.6
    events = [NoteEvent(60 + i, i * 0.5 * spb, (i * 0.5 + 0.5) * spb, 80) for i in range(8)]
    q = quantize.quantize_cost(events, grid)
    fid = notation_fidelity(events, q, grid)
    assert fid["onset"] == 1.0
    assert fid["duration"] == 1.0
    assert fid["median_shift_beats"] < 0.02


def test_fidelity_drops_when_notation_misrepresents_timing():
    """A score that moves notes far from where they were played scores lower."""
    from piano_transcribe.evaluate import notation_fidelity

    grid = _grid()
    spb = 0.6
    events = [NoteEvent(60 + i, i * 0.5 * spb, (i * 0.5 + 0.5) * spb, 80) for i in range(8)]
    q = quantize.quantize_cost(events, grid)
    for x in q:  # deliberately corrupt the notation
        x.onset_beats = x.onset_beats + F(1, 2)
        x.duration_beats = F(2)
    fid = notation_fidelity(events, q, grid)
    assert fid["duration"] < 0.5


# --- playback tempo ----------------------------------------------------------

def test_score_carries_the_performed_tempo():
    """A transcribed score records its tempo, so playback runs at the right speed.

    Regression: without a MetronomeMark music21 exports MIDI at its default 120
    BPM, so the rendered audio played at the wrong speed and the follow-along
    cursor drifted away from the sound.
    """
    from piano_transcribe import notate, spelling, voices

    bpm = 96.0
    spb = 60.0 / bpm
    grid = BeatGrid(beat_times_s=[i * spb for i in range(16)], beats_per_bar=4)
    assert grid.tempo_bpm == pytest.approx(bpm)

    events = [NoteEvent(60 + i, i * spb, (i + 1) * spb, 80) for i in range(8)]
    q = quantize.quantize_nearest(events, grid)
    voices.assign_middle_c_split(q)
    score = notate.build_score(q, grid, spelling.estimate_key(events))

    marks = list(score.flatten().getElementsByClass("MetronomeMark"))
    assert marks, "score has no tempo marking"
    assert float(marks[0].number) == pytest.approx(bpm, rel=0.01)


def test_tempo_bpm_ignores_a_single_odd_beat():
    """One mis-tracked beat shouldn't skew the reported tempo (median, not mean)."""
    times = [0.0, 0.5, 1.0, 1.5, 2.0, 4.0]  # last gap is a tracking glitch
    assert BeatGrid(beat_times_s=times).tempo_bpm == pytest.approx(120.0)
