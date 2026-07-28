"""Key estimation + enharmonic spelling.

Two steps:
  1. **Key estimation** via Krumhansl-Schmuckler: correlate the piece's
     pitch-class histogram against the 24 major/minor key profiles, pick the
     best-correlating key.
  2. **Spelling**: choose each note's enharmonic name (C# vs Db, etc.) to
     minimise accidentals *within the estimated key* — prefer diatonic
     spellings, keep chromatic notes consistent within a measure.

Fewer accidentals directly lowers the tier-3 complexity metric.

Baseline (implemented): duration-weighted key estimate, then global sharp/flat
spelling chosen from the key signature. Per-measure enharmonic consistency is
the refinement.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .types import NoteEvent

# Krumhansl-Kessler major / minor key profiles (tonic-relative weights).
KS_MAJOR_PROFILE = (
    6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88,
)
KS_MINOR_PROFILE = (
    6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17,
)


@dataclass
class KeyEstimate:
    """An estimated key.

    Attributes:
        tonic_pc: Tonic pitch class, 0=C .. 11=B.
        mode: ``"major"`` or ``"minor"``.
        correlation: Krumhansl-Schmuckler correlation of the winning profile.
    """

    tonic_pc: int
    mode: str
    correlation: float

    @property
    def _reference_major_pc(self) -> int:
        """Pitch class of the parallel/relative *major* that fixes the key sig.

        A minor key shares its signature with the major a minor-third up.
        """
        return self.tonic_pc if self.mode == "major" else (self.tonic_pc + 3) % 12

    @property
    def key_signature_sharps(self) -> int:
        """Signed accidental count for a music21 ``KeySignature`` (- == flats)."""
        fifths = (self._reference_major_pc * 7) % 12  # 0..11 on circle of 5ths
        return fifths if fifths <= 6 else fifths - 12

    @property
    def uses_flats(self) -> bool:
        return self.key_signature_sharps < 0

    @property
    def tonic_name(self) -> str:
        names = _FLAT_NAMES if self.uses_flats else _SHARP_NAMES
        return names[self.tonic_pc]

    @property
    def name(self) -> str:
        return f"{self.tonic_name} {self.mode}"


# music21 spelling: '#' = sharp, '-' = flat.
_SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLAT_NAMES = ("C", "D-", "D", "E-", "E", "F", "G-", "G", "A-", "A", "B-", "B")


def _pearson(a, b) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def estimate_key(events: list[NoteEvent]) -> KeyEstimate:
    """Estimate the key via Krumhansl-Schmuckler profile correlation.

    Builds a duration-weighted pitch-class histogram, correlates it against all
    24 rotated major/minor profiles, and returns the best-correlating key.
    Empty input defaults to C major.
    """
    histogram = np.zeros(12, dtype=float)
    for event in events:
        histogram[event.pitch % 12] += max(event.duration_s, 1e-6)

    if histogram.sum() == 0:
        return KeyEstimate(tonic_pc=0, mode="major", correlation=0.0)

    best: KeyEstimate | None = None
    for mode, profile in (("major", KS_MAJOR_PROFILE), ("minor", KS_MINOR_PROFILE)):
        base = np.asarray(profile, dtype=float)
        for tonic in range(12):
            corr = _pearson(histogram, np.roll(base, tonic))
            if best is None or corr > best.correlation:
                best = KeyEstimate(tonic_pc=tonic, mode=mode, correlation=corr)

    assert best is not None
    return best


def spell_notes(events: list[NoteEvent], key: KeyEstimate) -> list[str]:
    """Return a music21-style note name with octave (e.g. ``"F#4"``) per event.

    Baseline: pick sharp or flat spellings globally based on the key signature
    (sharp keys spell black keys as sharps, flat keys as flats), which keeps the
    common case free of unnecessary accidentals. Per-measure consistency and
    double accidentals are the refinement.
    """
    names = _FLAT_NAMES if key.uses_flats else _SHARP_NAMES
    spelled: list[str] = []
    for event in events:
        octave = event.pitch // 12 - 1  # MIDI 60 -> C4
        spelled.append(f"{names[event.pitch % 12]}{octave}")
    return spelled
