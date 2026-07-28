"""Note events + beat grid -> notated durations on a metrical grid.

The heart of the project. This is what tier-2 (rhythmic accuracy) and tier-3
(notation complexity) metrics actually move.

Two implementations, in order:

1. **Baseline (implemented)** — map each onset/offset to a fractional beat
   position via the grid, then snap to the nearest grid subdivision
   (``resolution``, a fraction of a quarter-note beat). Fast, dumb, and the
   thing every better version must beat.

2. **Cost-based (stub)** — search candidate quantizations per beat and
   minimise::

       total_cost = alpha * timing_displacement
                  + beta  * notational_complexity

   penalising tuplets, ties across beats/barlines, and very short
   subdivisions.
"""

from __future__ import annotations

import math
from collections import defaultdict
from fractions import Fraction

from .beats import seconds_to_beats
from .types import BeatGrid, NoteEvent, QuantizedNote

# Candidate subdivisions of a single beat the cost search may consider, as
# fractions of a quarter-note beat. Includes duplet and triplet families.
DEFAULT_SUBDIVISIONS: tuple[Fraction, ...] = (
    Fraction(1, 1),   # quarter
    Fraction(1, 2),   # eighth
    Fraction(1, 3),   # eighth triplet
    Fraction(1, 4),   # sixteenth
    Fraction(1, 6),   # sixteenth triplet
    Fraction(1, 8),   # thirty-second
)


def _snap(beat_pos: float, resolution: Fraction) -> Fraction:
    """Round a fractional beat position to the nearest multiple of ``resolution``."""
    steps = round(beat_pos / float(resolution))
    return Fraction(steps) * resolution


def quantize_nearest(
    events: list[NoteEvent],
    grid: BeatGrid,
    resolution: Fraction = Fraction(1, 4),
) -> list[QuantizedNote]:
    """Baseline: snap onsets/offsets to the nearest grid subdivision.

    ``resolution`` is the grid step in quarter-note beats (default 1/4 beat ==
    a sixteenth-note grid). The whole piece is shifted so the earliest note
    lands on beat 0, which keeps music21 offsets non-negative and measures
    starting cleanly.

    Returns quantized notes in the same order as ``events``.
    """
    if not events:
        return []

    onset_beats = seconds_to_beats(grid, [e.onset_s for e in events])
    offset_beats = seconds_to_beats(grid, [e.offset_s for e in events])

    quantized: list[QuantizedNote] = []
    for event, on, off in zip(events, onset_beats, offset_beats):
        on_q = _snap(float(on), resolution)
        off_q = _snap(float(off), resolution)
        duration = off_q - on_q
        if duration <= 0:
            duration = resolution  # never emit a zero/negative-length note
        quantized.append(
            QuantizedNote(event=event, onset_beats=on_q, duration_beats=duration)
        )

    # Shift so the earliest onset is beat 0 (non-negative metrical positions).
    shift = min(q.onset_beats for q in quantized)
    if shift != 0:
        for q in quantized:
            q.onset_beats -= shift

    return quantized


def _subdivision_complexity(s: Fraction) -> float:
    """Notational cost of using subdivision ``s`` (a fraction of a beat).

    Finer grids cost more (``log2`` of the number of divisions), and triplet /
    tuplet families carry an extra penalty — the readability tax the metric
    tier-3 later measures.
    """
    per_beat = 1.0 / float(s)
    complexity = math.log2(per_beat) if per_beat > 1 else 0.0
    if s.denominator % 3 == 0:  # 1/3, 1/6, ... -> tuplets
        complexity += 1.0
    return complexity


# Grid used for beats that contain no events at all (nothing normally snaps
# there, but a fallback must still be representable — never a whole beat).
FALLBACK_SUBDIVISION = Fraction(1, 4)


def quantize_cost(
    events: list[NoteEvent],
    grid: BeatGrid,
    alpha: float = 8.0,
    beta: float = 1.5,
    subdivisions: tuple[Fraction, ...] = DEFAULT_SUBDIVISIONS,
) -> list[QuantizedNote]:
    """Cost-based quantization: minimise displacement + notational complexity.

    For each beat, every event *time point* falling inside it — onsets **and**
    offsets — is a point the grid has to represent. The chosen subdivision
    minimises::

        cost(beat) = alpha * sum |point - snapped(point)|   (timing displacement)
                   + beta  * complexity(subdivision)        (readability)

    Two details matter for accuracy, and both were wrong in the first version:

    * **Offsets count.** A beat holding only the tail of an eighth note still
      needs an eighth grid; choosing on onsets alone rounded such durations to
      whole beats.
    * **Complexity is per-beat, not per-note.** Multiplying it by the note count
      made finer grids progressively more expensive the busier a beat was, so
      dense passages collapsed onto quarter-note positions.

    Args:
        alpha: Weight on timing fidelity. Higher -> follow the performance,
            accept messier notation (more tuplets/short values).
        beta: Weight on readability. Higher -> cleaner, coarser notation.

    ``alpha``/``beta`` are tuned against ``python -m cli.bench_quantize``; the
    defaults keep straight duple rhythms exact while still buying triplets when
    the performed timing genuinely needs them. Returns quantized notes in the
    same order as ``events``.
    """
    if not events:
        return []

    onset_beats = seconds_to_beats(grid, [e.onset_s for e in events])
    offset_beats = seconds_to_beats(grid, [e.offset_s for e in events])

    # Every point the grid must represent, bucketed by the beat it falls in.
    beat_points: dict[int, list[float]] = defaultdict(list)
    for pos in (*onset_beats, *offset_beats):
        beat = math.floor(pos)
        beat_points[beat].append(pos - beat)

    # Cheapest subdivision per populated beat (ties prefer the coarser grid,
    # since `subdivisions` runs coarse -> fine and `<` keeps the incumbent).
    chosen: dict[int, Fraction] = {}
    for beat, fracs in beat_points.items():
        best_s, best_cost = subdivisions[0], math.inf
        for s in subdivisions:
            step = float(s)
            displacement = sum(abs(f - round(f / step) * step) for f in fracs)
            cost = alpha * displacement + beta * _subdivision_complexity(s)
            if cost < best_cost:
                best_s, best_cost = s, cost
        chosen[beat] = best_s

    def snap(pos: float) -> Fraction:
        beat = math.floor(pos)
        s = chosen.get(beat, FALLBACK_SUBDIVISION)
        k = round((pos - beat) / float(s))
        return Fraction(beat) + Fraction(k) * s

    quantized: list[QuantizedNote] = []
    for i, event in enumerate(events):
        on_q = snap(onset_beats[i])
        off_q = snap(offset_beats[i])
        duration = off_q - on_q
        if duration <= 0:
            # Never emit a zero-length note: give it the finest grid step in play.
            duration = min(
                chosen.get(math.floor(onset_beats[i]), FALLBACK_SUBDIVISION),
                FALLBACK_SUBDIVISION,
            )
        quantized.append(
            QuantizedNote(event=event, onset_beats=on_q, duration_beats=duration)
        )

    shift = min(q.onset_beats for q in quantized)
    if shift != 0:
        for q in quantized:
            q.onset_beats -= shift

    return quantized
