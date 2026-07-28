"""Rhythm benchmark for the notation layer (beats -> quantize).

The point of this project is a *measurable* readability claim, so accuracy work
needs a number to move. This benchmark isolates the part we control — beat
tracking and quantization — from the transcription model:

  1. take synthetic pieces whose true rhythm is known exactly (in beats),
  2. render them to note events at a tempo, with human-like timing jitter,
  3. run them through the real quantizer,
  4. compare the *notated* onsets/durations against the truth.

Two grid modes:
  ``perfect`` — a mathematically exact beat grid (isolates the quantizer),
  ``tracked`` — a grid recovered from the events (adds beat-tracking error).

Usage:
    python -m cli.bench_quantize
    python -m cli.bench_quantize --jitter 0.03 --quantizer cost
"""

from __future__ import annotations

import argparse
import random
from fractions import Fraction

from piano_transcribe import quantize
from piano_transcribe.types import BeatGrid, NoteEvent

F = Fraction

# --- test corpus: (name, [(onset_beats, duration_beats, pitch), ...]) --------
# Durations/onsets are exact fractions of a quarter-note beat.


def _seq(durations, pitches=None, start=F(0)):
    """Build a sequential melody from a list of durations."""
    pitches = pitches or [60 + (i % 8) for i in range(len(durations))]
    out, t = [], start
    for d, p in zip(durations, pitches):
        out.append((t, d, p))
        t += d
    return out


CORPUS = {
    "quarters": _seq([F(1)] * 8),
    "eighths": _seq([F(1, 2)] * 16),
    "sixteenths": _seq([F(1, 4)] * 16),
    "dotted": _seq([F(3, 2), F(1, 2)] * 4),
    "syncopation": _seq([F(1, 2), F(1), F(1), F(1, 2)] * 2),
    "mixed": _seq([F(1), F(1, 2), F(1, 2), F(1, 4), F(1, 4), F(1, 2), F(2)] * 2),
    "triplets": _seq([F(1, 3)] * 12),
    "long_notes": _seq([F(4), F(2), F(2), F(4)]),
    "melody_over_held": (
        # A held bass note under a moving line: exercises offsets that land in
        # beats containing no onsets.
        [(F(0), F(4), 48), (F(4), F(4), 43)]
        + _seq([F(1, 2)] * 16, pitches=[72, 74, 76, 77] * 4)
    ),
    "chords": [
        (F(b), F(1), p)
        for b in range(8)
        for p in ((60, 64, 67) if b % 2 == 0 else (59, 62, 67))
    ],
}


def to_events(truth, bpm: float, jitter_s: float, rng: random.Random):
    """Render (onset_beats, dur_beats, pitch) truth to timed NoteEvents."""
    spb = 60.0 / bpm
    events = []
    for onset_b, dur_b, pitch in truth:
        on = float(onset_b) * spb + rng.gauss(0, jitter_s)
        off = on + float(dur_b) * spb + rng.gauss(0, jitter_s * 0.5)
        events.append(NoteEvent(pitch, max(0.0, on), max(0.001, off), 80))
    order = sorted(range(len(events)), key=lambda i: (events[i].onset_s, events[i].pitch))
    return [events[i] for i in order], [truth[i] for i in order]


def perfect_grid(truth, bpm: float) -> BeatGrid:
    spb = 60.0 / bpm
    total = max(float(o) + float(d) for o, d, _ in truth)
    n = int(total) + 4
    beats = [i * spb for i in range(n)]
    return BeatGrid(beat_times_s=beats, downbeats_s=beats[::4], beats_per_bar=4, beat_unit=4)


def tracked_grid(events, bpm_hint: float) -> BeatGrid:
    """Recover a grid from note onsets (no audio) — approximates beat tracking."""
    from piano_transcribe.beats import grid_from_onsets

    return grid_from_onsets([e.onset_s for e in events], bpm_hint=bpm_hint)


def score(truth, quantized) -> tuple[float, float]:
    """Return (onset_accuracy, duration_accuracy) against the truth."""
    if not quantized:
        return 0.0, 0.0
    t_shift = min(o for o, _, _ in truth)
    q_shift = min(q.onset_beats for q in quantized)
    on_ok = dur_ok = 0
    for (t_on, t_dur, _), q in zip(truth, quantized):
        if (t_on - t_shift) == (q.onset_beats - q_shift):
            on_ok += 1
        if t_dur == q.duration_beats:
            dur_ok += 1
    n = len(quantized)
    return on_ok / n, dur_ok / n


def run(quantizer: str, jitter: float, bpm: float, grid_mode: str, seed: int = 7):
    rng = random.Random(seed)
    fn = quantize.quantize_cost if quantizer == "cost" else quantize.quantize_nearest
    rows = []
    for name, truth in CORPUS.items():
        events, ordered_truth = to_events(truth, bpm, jitter, rng)
        grid = (
            perfect_grid(truth, bpm) if grid_mode == "perfect"
            else tracked_grid(events, bpm)
        )
        q = fn(events, grid)
        on_acc, dur_acc = score(ordered_truth, q)
        rows.append((name, on_acc, dur_acc))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark rhythm notation accuracy.")
    ap.add_argument("--quantizer", choices=["cost", "nearest"], default="cost")
    ap.add_argument("--jitter", type=float, default=0.02, help="timing noise sigma (s)")
    ap.add_argument("--bpm", type=float, default=100.0)
    ap.add_argument("--grid", choices=["perfect", "tracked"], default="perfect")
    args = ap.parse_args()

    rows = run(args.quantizer, args.jitter, args.bpm, args.grid)
    print(f"quantizer={args.quantizer} jitter={args.jitter}s bpm={args.bpm} grid={args.grid}")
    print(f"{'piece':<18}{'onset%':>9}{'duration%':>11}")
    print("-" * 38)
    for name, on, dur in rows:
        print(f"{name:<18}{on * 100:>8.1f}{dur * 100:>11.1f}")
    n = len(rows)
    print("-" * 38)
    print(f"{'MEAN':<18}{sum(r[1] for r in rows) / n * 100:>8.1f}"
          f"{sum(r[2] for r in rows) / n * 100:>11.1f}")


if __name__ == "__main__":
    main()
