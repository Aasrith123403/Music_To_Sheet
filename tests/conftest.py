"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest

from piano_transcribe.types import NoteEvent


@pytest.fixture
def c_major_scale() -> list[NoteEvent]:
    """One octave of C major, quarter notes at 120 BPM (0.5 s each)."""
    pitches = [60, 62, 64, 65, 67, 69, 71, 72]  # C4 .. C5
    return [
        NoteEvent(pitch=p, onset_s=i * 0.5, offset_s=i * 0.5 + 0.5, velocity=80)
        for i, p in enumerate(pitches)
    ]
