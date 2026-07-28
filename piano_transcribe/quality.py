"""Best-effort gate: is this audio worth trying to notate?

Single-instrument transcription fails badly on the wrong input — speech, dense
full-band mixes, silence. These heuristics reject the obvious cases with a
human-readable reason so the UI can decline gracefully instead of returning a
page of nonsense notes. They are deliberately conservative (only reject when
clearly hopeless); they are *not* a genre or quality classifier.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analyze import _max_polyphony
from .types import NoteEvent

MAX_DURATION_S = 10 * 60  # 10 minutes
MIN_NOTES = 8
MAX_POLYPHONY = 16  # more simultaneous notes than two hands / an ensemble mix


@dataclass
class Verdict:
    ok: bool
    reason: str


def assess_duration(duration_s: float) -> Verdict:
    """Pre-download check usable from metadata alone (before transcription)."""
    if duration_s > MAX_DURATION_S:
        mins = duration_s / 60
        return Verdict(False, f"Clip is {mins:.1f} min long; the limit is 10 minutes.")
    if duration_s <= 0:
        return Verdict(False, "Could not read the audio duration.")
    return Verdict(True, "ok")


def assess_transcription(events: list[NoteEvent], duration_s: float) -> Verdict:
    """Post-transcription check on the detected note events."""
    dur = assess_duration(duration_s)
    if not dur.ok:
        return dur
    if len(events) < MIN_NOTES:
        return Verdict(
            False,
            "Too few pitched notes were detected — this doesn't look like "
            "single-instrument music (it may be speech, percussion, or noise).",
        )
    max_poly = _max_polyphony(events)
    if max_poly > MAX_POLYPHONY:
        return Verdict(
            False,
            "The audio is too dense to transcribe as a single instrument — it "
            "sounds like a full mix or ensemble. Try an isolated solo recording.",
        )
    return Verdict(True, "ok")
