"""Metrics for the pipeline.

Three tiers, because the obvious metric (note accuracy) measures the *model*,
not the notation work:

1. **Note accuracy** — onset F1 and onset+offset F1 via
   ``mir_eval.transcription``. Implemented here.
2. **Rhythmic accuracy** — fraction of notes given the correct notated
   duration vs. ground-truth MIDI quantized on the same grid. Moved by the
   quantizer; see :func:`rhythmic_accuracy` (needs quantize.py filled in).
3. **Notation complexity** — tuplets, ties across barlines, accidentals per
   measure. Lower is better at equal rhythmic accuracy; see
   :func:`notation_complexity` (needs notate.py filled in).

This module also provides the dataset harness used by ``cli/run_eval.py`` to
score a MAESTRO subset and write a CSV.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .types import NoteEvent, midi_to_hz

# ---------------------------------------------------------------------------
# Tier 1: note accuracy (mir_eval)
# ---------------------------------------------------------------------------


def note_events_to_mireval(
    events: list[NoteEvent],
) -> tuple[np.ndarray, np.ndarray]:
    """Convert ``NoteEvent``s to mir_eval's ``(intervals, pitches)`` form.

    Returns:
        intervals: ``(N, 2)`` float array of ``[onset_s, offset_s]`` rows.
        pitches: ``(N,)`` float array of frequencies in Hz.

    Empty input yields correctly-shaped empty arrays so mir_eval can still be
    called (it treats an empty estimate as all-misses).
    """
    if not events:
        return np.zeros((0, 2), dtype=float), np.zeros((0,), dtype=float)
    intervals = np.array([[e.onset_s, e.offset_s] for e in events], dtype=float)
    pitches = np.array([midi_to_hz(e.pitch) for e in events], dtype=float)
    return intervals, pitches


@dataclass
class TranscriptionMetrics:
    """Precision / recall / F1 for onset-only and onset+offset matching."""

    onset_precision: float
    onset_recall: float
    onset_f1: float
    onset_offset_precision: float
    onset_offset_recall: float
    onset_offset_f1: float
    n_reference: int
    n_estimate: int

    def as_row(self) -> dict[str, float | int]:
        return {
            "onset_precision": round(self.onset_precision, 4),
            "onset_recall": round(self.onset_recall, 4),
            "onset_f1": round(self.onset_f1, 4),
            "onset_offset_precision": round(self.onset_offset_precision, 4),
            "onset_offset_recall": round(self.onset_offset_recall, 4),
            "onset_offset_f1": round(self.onset_offset_f1, 4),
            "n_reference": self.n_reference,
            "n_estimate": self.n_estimate,
        }


def evaluate_transcription(
    reference: list[NoteEvent],
    estimate: list[NoteEvent],
    onset_tolerance: float = 0.05,
    offset_ratio: float = 0.2,
    offset_min_tolerance: float = 0.05,
) -> TranscriptionMetrics:
    """Score ``estimate`` against ``reference`` with mir_eval.transcription.

    Two passes:
      * onset-only: a match needs pitch within a quarter-tone and onset within
        ``onset_tolerance`` seconds (offset ignored).
      * onset+offset: additionally requires the offset within
        ``max(offset_ratio * ref_duration, offset_min_tolerance)`` seconds.

    Scoring identical lists against each other returns F1 = 1.0 (the
    self-scoring sanity check the eval harness is built around).
    """
    import mir_eval

    ref_intervals, ref_pitches = note_events_to_mireval(reference)
    est_intervals, est_pitches = note_events_to_mireval(estimate)

    # Onset-only: offset_ratio=None disables offset matching entirely.
    p_on, r_on, f_on, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_intervals,
        ref_pitches,
        est_intervals,
        est_pitches,
        onset_tolerance=onset_tolerance,
        offset_ratio=None,
    )

    # Onset + offset.
    p_onoff, r_onoff, f_onoff, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_intervals,
        ref_pitches,
        est_intervals,
        est_pitches,
        onset_tolerance=onset_tolerance,
        offset_ratio=offset_ratio,
        offset_min_tolerance=offset_min_tolerance,
    )

    return TranscriptionMetrics(
        onset_precision=float(p_on),
        onset_recall=float(r_on),
        onset_f1=float(f_on),
        onset_offset_precision=float(p_onoff),
        onset_offset_recall=float(r_onoff),
        onset_offset_f1=float(f_onoff),
        n_reference=len(reference),
        n_estimate=len(estimate),
    )


# ---------------------------------------------------------------------------
# Tier 2: rhythmic accuracy (depends on quantize.py)
# ---------------------------------------------------------------------------


def _match_by_pitch_onset(reference, estimate, onset_tolerance):
    """Greedy one-to-one match on identical pitch + nearest onset (seconds).

    Uses each note's underlying ``event`` onset so it works on ``QuantizedNote``s
    regardless of how their metrical positions were assigned. Returns a list of
    ``(ref, est)`` pairs.
    """
    used = [False] * len(estimate)
    pairs = []
    for ref in reference:
        best_j, best_d = None, onset_tolerance + 1.0
        for j, est in enumerate(estimate):
            if used[j] or est.event.pitch != ref.event.pitch:
                continue
            d = abs(est.event.onset_s - ref.event.onset_s)
            if d <= onset_tolerance and d < best_d:
                best_j, best_d = j, d
        if best_j is not None:
            used[best_j] = True
            pairs.append((ref, estimate[best_j]))
    return pairs


def rhythmic_accuracy(
    reference_quantized,  # list[QuantizedNote]
    estimate_quantized,  # list[QuantizedNote]
    onset_tolerance: float = 0.05,
) -> float:
    """Fraction of matched notes whose *notated duration* is correct.

    Match reference/estimate notes by pitch + onset (same rule as tier 1), then
    among matched pairs count how many share the exact same ``duration_beats``.
    This is the number the quantizer directly moves.

    Returns 0.0 when nothing matches (no shared notes to judge rhythm on).
    """
    pairs = _match_by_pitch_onset(
        reference_quantized, estimate_quantized, onset_tolerance
    )
    if not pairs:
        return 0.0
    correct = sum(1 for ref, est in pairs if ref.duration_beats == est.duration_beats)
    return correct / len(pairs)


# ---------------------------------------------------------------------------
# Tier 3: notation complexity (depends on notate.py)
# ---------------------------------------------------------------------------


def notation_fidelity(
    events: list[NoteEvent],
    quantized,  # list[QuantizedNote]
    grid,       # BeatGrid
    tolerance_beats: float = 0.125,
) -> dict:
    """How faithfully does the written score represent what was actually heard?

    Compares each note's *performed* position (in beats, via the beat grid)
    against the position it was **notated** at, and reports the fraction that
    landed within ``tolerance_beats`` (default: a 32nd note).

    This needs no ground truth, so it can be reported for every job — but be
    clear about what it does and doesn't cover:

    * it **does** measure the notation layer (beat grid + quantizer): a low
      score means the score misrepresents the performance's rhythm;
    * it does **not** measure whether the transcription model heard the right
      notes. A perfect score over hallucinated notes is still perfect nonsense.

    For that second half, listen to the score played back, or run
    ``cli.run_eval`` against ground-truth MIDI.
    """
    from .beats import seconds_to_beats

    if not events or not quantized:
        return {"onset": None, "duration": None, "median_shift_beats": None}

    raw_on = seconds_to_beats(grid, [e.onset_s for e in events])
    raw_off = seconds_to_beats(grid, [e.offset_s for e in events])

    # Both sequences are anchored to their own first note, since the quantizer
    # shifts the piece to start at beat 0.
    raw_shift = float(np.min(raw_on))
    q_shift = float(min(q.onset_beats for q in quantized))

    onset_ok = dur_ok = 0
    shifts = []
    for i, q in enumerate(quantized):
        played_on = float(raw_on[i]) - raw_shift
        played_dur = float(raw_off[i]) - float(raw_on[i])
        written_on = float(q.onset_beats) - q_shift
        written_dur = float(q.duration_beats)

        shift = abs(played_on - written_on)
        shifts.append(shift)
        if shift <= tolerance_beats:
            onset_ok += 1
        if abs(played_dur - written_dur) <= tolerance_beats:
            dur_ok += 1

    n = len(quantized)
    return {
        "onset": round(onset_ok / n, 3),
        "duration": round(dur_ok / n, 3),
        "median_shift_beats": round(float(np.median(shifts)), 3),
    }


@dataclass
class ComplexityCounts:
    """Readability proxy — all "lower is better" at equal rhythmic accuracy."""

    tuplets: int
    ties_across_barlines: int
    accidentals: int
    measures: int

    @property
    def accidentals_per_measure(self) -> float:
        return self.accidentals / self.measures if self.measures else 0.0


def notation_complexity(score) -> ComplexityCounts:
    """Count tuplets, cross-barline ties, and accidentals in a music21 Score.

    Walks every part's measures:
      * **tuplets** — notes whose duration carries a tuplet bracket,
      * **ties across barlines** — a tie starting on a note that reaches the end
        of its measure (i.e. it continues into the next bar),
      * **accidentals** — displayed accidentals on any sounding pitch.

    ``measures`` is the musical measure count (max over parts, so the two
    staves of a grand staff count once), giving a meaningful per-measure rate.
    """
    parts = list(score.parts)
    tuplets = ties = accidentals = 0
    measures = max((len(p.getElementsByClass("Measure")) for p in parts), default=0)

    for part in parts:
        for measure in part.getElementsByClass("Measure"):
            bar_len = measure.barDuration.quarterLength
            for n in measure.notes:  # Note or Chord
                for pitch in n.pitches:
                    acc = pitch.accidental
                    if acc is not None and acc.displayStatus:
                        accidentals += 1
                if n.duration.tuplets:
                    tuplets += 1
                tie = getattr(n, "tie", None)
                reaches_barline = abs(n.offset + n.quarterLength - bar_len) < 1e-6
                if tie is not None and tie.type in ("start", "continue") and reaches_barline:
                    ties += 1

    return ComplexityCounts(
        tuplets=tuplets, ties_across_barlines=ties,
        accidentals=accidentals, measures=measures,
    )


# ---------------------------------------------------------------------------
# Dataset harness
# ---------------------------------------------------------------------------


def evaluate_dataset(
    pairs: list[tuple[str, list[NoteEvent], list[NoteEvent]]],
    out_csv: str | Path | None = None,
) -> list[dict]:
    """Score many (name, reference, estimate) triples and optionally write CSV.

    ``cli/run_eval.py`` builds ``pairs`` from a MAESTRO subset: reference from
    the ground-truth MIDI, estimate from running the pipeline on the audio.

    Returns one metrics row per piece; when ``out_csv`` is given, also writes a
    CSV with a trailing mean row.
    """
    rows: list[dict] = []
    for name, reference, estimate in pairs:
        metrics = evaluate_transcription(reference, estimate)
        row = {"piece": name, **metrics.as_row()}
        rows.append(row)

    if out_csv is not None and rows:
        _write_csv_with_mean(rows, Path(out_csv))
    return rows


def _write_csv_with_mean(rows: list[dict], out_csv: Path) -> None:
    numeric_keys = [k for k, v in rows[0].items() if isinstance(v, (int, float))]
    mean_row = {"piece": "MEAN"}
    for k in numeric_keys:
        mean_row[k] = round(float(np.mean([r[k] for r in rows])), 4)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        writer.writerow(mean_row)
