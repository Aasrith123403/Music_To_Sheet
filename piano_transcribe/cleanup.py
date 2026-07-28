"""Clean up raw transcription output before it becomes notation.

Neural transcribers optimise frame-level pitch detection, not readability, so
their raw output carries artifacts that turn into unreadable noise on a staff:

* **split notes** — one held note emitted as several fragments,
* **harmonic ghosts** — a quiet note an octave/twelfth above a loud one,
  detected from the lower note's overtones,
* **specks** — notes a few tens of milliseconds long that no one played.

Removing these raises precision (fewer wrong notes) and dramatically reduces
notational clutter. Every threshold is deliberately conservative: the cost of
deleting a real note is higher than the cost of keeping a spurious one, so the
filters only fire on clear-cut cases.
"""

from __future__ import annotations

from statistics import median

from .types import NoteEvent

# Intervals (semitones) at which overtones of a low note get mis-detected:
# octave, octave+fifth, two octaves, +major third, +fifth.
HARMONIC_INTERVALS = frozenset({12, 19, 24, 28, 31})


def merge_split_notes(
    events: list[NoteEvent],
    max_gap_s: float = 0.06,
    max_fragment_s: float = 0.1,
) -> list[NoteEvent]:
    """Absorb short same-pitch fragments left over from a split detection.

    Deliberately conservative: only a *fragment* (shorter than
    ``max_fragment_s``) is absorbed into the note before it. Merging on the gap
    alone would fuse genuinely repeated notes — a repeated bass note held for
    its full beat leaves no gap at all, and swallowing those onsets was measured
    to cost far more recall than the split-note repair gained.
    """
    by_pitch: dict[int, list[NoteEvent]] = {}
    for e in events:
        by_pitch.setdefault(e.pitch, []).append(e)

    merged: list[NoteEvent] = []
    for pitch, group in by_pitch.items():
        group.sort(key=lambda e: e.onset_s)
        current = group[0]
        for nxt in group[1:]:
            gap = nxt.onset_s - current.offset_s
            if gap <= max_gap_s and nxt.duration_s < max_fragment_s:
                current = NoteEvent(
                    pitch,
                    current.onset_s,
                    max(current.offset_s, nxt.offset_s),
                    max(current.velocity, nxt.velocity),
                )
            else:
                merged.append(current)
                current = nxt
        merged.append(current)

    merged.sort(key=lambda e: (e.onset_s, e.pitch))
    return merged


def drop_short_notes(events: list[NoteEvent], min_duration_s: float = 0.05) -> list[NoteEvent]:
    """Remove notes too short to have been played deliberately."""
    return [e for e in events if e.duration_s >= min_duration_s]


def drop_harmonic_ghosts(
    events: list[NoteEvent],
    velocity_ratio: float = 0.55,
    onset_tol_s: float = 0.05,
) -> list[NoteEvent]:
    """Drop quiet notes that look like overtones of a louder simultaneous note.

    A note is only removed when *all* of these hold: it sits a harmonic interval
    above a note that starts at essentially the same time, it is markedly
    quieter, and it ends no later than that note. Genuine octave doubling
    survives because a real doubled note is played at a comparable velocity.
    """
    kept: list[NoteEvent] = []
    for e in events:
        ghost = False
        for other in events:
            if other is e or other.pitch >= e.pitch:
                continue
            if (e.pitch - other.pitch) not in HARMONIC_INTERVALS:
                continue
            if abs(other.onset_s - e.onset_s) > onset_tol_s:
                continue
            if e.offset_s > other.offset_s + onset_tol_s:
                continue
            if e.velocity < velocity_ratio * other.velocity:
                ghost = True
                break
        if not ghost:
            kept.append(e)
    return kept


def drop_quiet_outliers(events: list[NoteEvent], ratio: float = 0.3) -> list[NoteEvent]:
    """Remove notes far quieter than the piece's typical level."""
    if len(events) < 8:
        return events
    threshold = ratio * median(e.velocity for e in events)
    return [e for e in events if e.velocity >= threshold]


def clean_events(
    events: list[NoteEvent],
    min_duration_s: float = 0.05,
    max_gap_s: float = 0.06,
    drop_ghosts: bool = True,
) -> list[NoteEvent]:
    """Run the full cleanup chain, ordered so each stage helps the next.

    Merging first means a note split into specks is repaired rather than
    deleted by the short-note filter.
    """
    if not events:
        return []
    out = merge_split_notes(events, max_gap_s=max_gap_s)
    out = drop_short_notes(out, min_duration_s=min_duration_s)
    if drop_ghosts:
        out = drop_harmonic_ghosts(out)
    out = drop_quiet_outliers(out)
    out.sort(key=lambda e: (e.onset_s, e.pitch))
    return out
