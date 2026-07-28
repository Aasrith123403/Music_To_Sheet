"""Summarise a transcription for the analysis panel.

Turns the note events + beat grid + key estimate into a flat, JSON-serialisable
dict: duration, tempo, time signature, key/scale, pitch range, texture,
dynamics, and the most-used pitch classes. All derived from data the pipeline
already computed — no extra audio passes.
"""

from __future__ import annotations

from collections import Counter

from .beats import BeatGrid
from .spelling import KeyEstimate, _FLAT_NAMES, _SHARP_NAMES
from .types import NoteEvent

_MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
_MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)  # natural minor


def _pitch_name(midi: int, use_flats: bool) -> str:
    names = _FLAT_NAMES if use_flats else _SHARP_NAMES
    return f"{names[midi % 12]}{midi // 12 - 1}"


def _scale_names(key: KeyEstimate) -> list[str]:
    steps = _MAJOR_STEPS if key.mode == "major" else _MINOR_STEPS
    names = _FLAT_NAMES if key.uses_flats else _SHARP_NAMES
    return [names[(key.tonic_pc + s) % 12] for s in steps]


def _tempo_bpm(grid: BeatGrid) -> float | None:
    times = grid.beat_times_s
    if len(times) < 2:
        return None
    diffs = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not diffs:
        return None
    diffs.sort()
    median = diffs[len(diffs) // 2]
    return round(60.0 / median, 1) if median > 0 else None


def _max_polyphony(events: list[NoteEvent]) -> int:
    """Maximum number of notes sounding simultaneously (sweep line)."""
    points = []
    for e in events:
        points.append((e.onset_s, 1))
        points.append((e.offset_s, -1))
    # Process offsets before onsets at the same instant so touching notes
    # aren't counted as overlapping.
    points.sort(key=lambda p: (p[0], p[1]))
    cur = best = 0
    for _t, delta in points:
        cur += delta
        best = max(best, cur)
    return best


def _hms(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def analyze(
    events: list[NoteEvent],
    grid: BeatGrid,
    key: KeyEstimate,
    duration_s: float | None = None,
) -> dict:
    """Return a JSON-serialisable summary of the transcription."""
    if duration_s is None:
        duration_s = max((e.offset_s for e in events), default=0.0)

    n = len(events)
    velocities = [e.velocity for e in events] or [0]
    pcs = Counter(e.pitch % 12 for e in events)
    use_flats = key.uses_flats
    pc_names = _FLAT_NAMES if use_flats else _SHARP_NAMES

    low = min((e.pitch for e in events), default=None)
    high = max((e.pitch for e in events), default=None)
    max_poly = _max_polyphony(events)

    return {
        "duration_s": round(duration_s, 2),
        "duration_hms": _hms(duration_s),
        "tempo_bpm": _tempo_bpm(grid),
        "time_signature": grid.time_signature,
        "key": key.name,
        "key_confidence": round(key.correlation, 3),
        "key_signature_sharps": key.key_signature_sharps,
        "scale": _scale_names(key),
        "num_notes": n,
        "notes_per_second": round(n / duration_s, 2) if duration_s > 0 else 0.0,
        "pitch_range": {
            "low": _pitch_name(low, use_flats) if low is not None else None,
            "high": _pitch_name(high, use_flats) if high is not None else None,
            "span_semitones": (high - low) if (low is not None and high is not None) else 0,
        },
        "texture": "monophonic" if max_poly <= 1 else "polyphonic",
        "max_polyphony": max_poly,
        "dynamics": {
            "min_velocity": min(velocities),
            "mean_velocity": round(sum(velocities) / len(velocities), 1),
            "max_velocity": max(velocities),
        },
        "top_pitch_classes": [
            {"name": pc_names[pc], "count": count}
            for pc, count in pcs.most_common(4)
        ],
    }
