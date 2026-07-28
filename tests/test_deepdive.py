"""Tests for the deep-dive stages: cost quantization, cost voices, eval
tiers 2-3, empty-staff notation, and MIDI loading."""

from __future__ import annotations

from fractions import Fraction

import pytest

from piano_transcribe import notate, quantize, spelling, voices
from piano_transcribe.evaluate import (
    ComplexityCounts,
    notation_complexity,
    rhythmic_accuracy,
)
from piano_transcribe.types import BeatGrid, NoteEvent


@pytest.fixture
def steady_grid() -> BeatGrid:
    """32 beats at 0.5 s each (120 BPM), 4/4."""
    beats = [i * 0.5 for i in range(32)]
    return BeatGrid(beat_times_s=beats, downbeats_s=beats[::4],
                    beats_per_bar=4, beat_unit=4)


# --- cost-based quantization ------------------------------------------------

def test_cost_quantizer_matches_baseline_on_clean_rhythm(c_major_scale, steady_grid):
    """On exact quarter notes the cost search should pick the coarse grid,
    giving the same integer beats as the baseline."""
    q = quantize.quantize_cost(c_major_scale, steady_grid)
    assert [x.onset_beats for x in q] == [Fraction(i) for i in range(len(c_major_scale))]
    assert all(x.duration_beats == Fraction(1) for x in q)


def test_cost_quantizer_can_represent_triplets(steady_grid):
    """Three evenly-spaced notes inside one beat, with accuracy-weighted
    settings, should be quantized onto a triplet grid (denominator 3) — which
    the fixed 1/4 baseline grid cannot represent."""
    # onsets at beats 0, 1/3, 2/3 -> seconds 0.0, 0.1667, 0.3333 on a 0.5s beat
    third = 0.5 / 3
    events = [
        NoteEvent(60, 0.0, third, 80),
        NoteEvent(62, third, 2 * third, 80),
        NoteEvent(64, 2 * third, 0.5, 80),
    ]
    q = quantize.quantize_cost(events, steady_grid, alpha=8.0, beta=0.5)
    denoms = {x.onset_beats.denominator for x in q}
    assert 3 in denoms  # a genuine triplet position was chosen


# --- cost-based voice assignment --------------------------------------------

def test_cost_voices_avoid_flipflop_on_brief_dip(steady_grid):
    """A treble line that dips one note below middle C should stay on the
    treble staff, unlike a hard middle-C split."""
    pitches = [72, 71, 59, 71, 72]  # 59 (B3) is just below middle C
    events = [NoteEvent(p, i * 0.5, i * 0.5 + 0.5, 80) for i, p in enumerate(pitches)]
    q = quantize.quantize_nearest(events, steady_grid)
    voices.assign_cost(q, switch_penalty=3.0)
    assert all(x.staff == 1 for x in q)  # never switched to bass

    # The naive baseline *does* send the dip to the bass staff.
    q2 = quantize.quantize_nearest(events, steady_grid)
    voices.assign_middle_c_split(q2)
    assert q2[2].staff == 2


def test_cost_voices_separate_clear_hands(steady_grid):
    """Clearly high and low notes still land on the expected staves."""
    events = [NoteEvent(84, 0.0, 0.5), NoteEvent(36, 0.0, 0.5),
              NoteEvent(81, 0.5, 1.0), NoteEvent(40, 0.5, 1.0)]
    q = quantize.quantize_nearest(events, steady_grid)
    voices.assign_cost(q)
    by_pitch = {x.event.pitch: x.staff for x in q}
    assert by_pitch[84] == 1 and by_pitch[81] == 1
    assert by_pitch[36] == 2 and by_pitch[40] == 2


# --- tier 2: rhythmic accuracy ----------------------------------------------

def test_rhythmic_accuracy_perfect_and_partial(c_major_scale, steady_grid):
    ref = quantize.quantize_nearest(c_major_scale, steady_grid)
    assert rhythmic_accuracy(ref, ref) == pytest.approx(1.0)

    # Corrupt one note's notated duration -> 7/8 correct.
    est = quantize.quantize_nearest(c_major_scale, steady_grid)
    est[0].duration_beats = Fraction(2)
    assert rhythmic_accuracy(ref, est) == pytest.approx(7 / 8)


def test_rhythmic_accuracy_no_matches_is_zero(steady_grid):
    a = quantize.quantize_nearest([NoteEvent(60, 0.0, 0.5)], steady_grid)
    b = quantize.quantize_nearest([NoteEvent(72, 5.0, 5.5)], steady_grid)
    assert rhythmic_accuracy(a, b) == 0.0


# --- tier 3: notation complexity --------------------------------------------

def test_notation_complexity_clean_scale(c_major_scale, steady_grid):
    q = quantize.quantize_nearest(c_major_scale, steady_grid)
    voices.assign_middle_c_split(q)
    key = spelling.estimate_key(c_major_scale)
    names = spelling.spell_notes(c_major_scale, key)
    score = notate.build_score(q, steady_grid, key, note_names=names)
    cx = notation_complexity(score)
    assert isinstance(cx, ComplexityCounts)
    assert cx.measures >= 1
    # A plain C-major scale needs no tuplets and no accidentals.
    assert cx.tuplets == 0
    assert cx.accidentals == 0


# --- empty-staff balancing --------------------------------------------------

def test_one_hand_passage_fills_both_staves(steady_grid):
    """All notes above middle C: the bass staff must still get measures/rests
    so the grand staff stays balanced."""
    events = [NoteEvent(72 + (i % 3), i * 0.5, i * 0.5 + 0.5, 80) for i in range(8)]
    q = quantize.quantize_nearest(events, steady_grid)
    voices.assign_middle_c_split(q)  # everything -> treble
    assert all(x.staff == 1 for x in q)
    key = spelling.estimate_key(events)
    score = notate.build_score(q, steady_grid, key)
    treble, bass = list(score.parts)
    n_treble = len(treble.getElementsByClass("Measure"))
    n_bass = len(bass.getElementsByClass("Measure"))
    assert n_bass == n_treble > 0  # bass wasn't left empty
