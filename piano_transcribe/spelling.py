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

# Key profiles: tonic-relative weights for how much each pitch class belongs to
# a key. The original Krumhansl-Kessler pair (1982) is kept for reference, but
# it is *not* used for the decision — it is known to be weak, and it was
# measured here calling an unambiguous A-minor melody "E major" (four wrong
# sharps on the page) purely because the dominant was the most frequent note.
KS_MAJOR_PROFILE = (
    6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88,
)
KS_MINOR_PROFILE = (
    6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17,
)

# Three later profile sets, each derived from a different corpus. All three get
# the above example right, and they disagree with each other on different kinds
# of music — so the estimate is a vote rather than any single set's opinion.
PROFILE_SETS = {
    # Aarden-Essen: European folk melodies.
    "aarden": (
        (17.7661, 0.14562, 14.9265, 0.16019, 19.8049, 11.3587,
         0.29125, 22.062, 0.14562, 8.15494, 0.233, 4.95122),
        (18.2648, 0.73762, 14.0499, 16.8599, 0.70249, 14.4362,
         0.70249, 18.6161, 4.56621, 1.93186, 7.37619, 1.75623),
    ),
    # Temperley / Kostka-Payne: common-practice tonal harmony.
    "temperley": (
        (0.748, 0.06, 0.488, 0.082, 0.67, 0.46, 0.096, 0.715, 0.104, 0.366,
         0.057, 0.4),
        (0.712, 0.084, 0.474, 0.618, 0.049, 0.46, 0.105, 0.747, 0.404, 0.067,
         0.133, 0.33),
    ),
    # Bellman-Budge: a broad tonal corpus.
    "bellman": (
        (16.8, 0.86, 12.95, 1.41, 13.49, 11.93, 1.25, 20.28, 1.8, 8.04,
         0.62, 10.57),
        (18.16, 0.69, 12.99, 13.34, 1.07, 11.15, 1.38, 21.07, 7.49, 1.53,
         0.92, 10.21),
    ),
}


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


def pitch_class_histogram(events: list[NoteEvent]) -> np.ndarray:
    """Duration-weighted pitch-class profile of a performance.

    Weighting by duration rather than note count matters: a held tonic says far
    more about the key than a passing sixteenth.
    """
    histogram = np.zeros(12, dtype=float)
    for event in events:
        histogram[event.pitch % 12] += max(event.duration_s, 1e-6)
    return histogram


def estimate_key(events: list[NoteEvent]) -> KeyEstimate:
    """Estimate the key by correlating against several published key profiles.

    Each profile set votes for its best-correlating key and the majority wins,
    with the summed correlation breaking ties. A vote is used because a single
    profile set fails in characteristic ways — the classic Krumhansl weights in
    particular mistake a minor key for the major a fifth above whenever the
    dominant is repeated a lot, which is extremely common (an A-minor melody
    dwelling on E came out as E major, putting four wrong sharps in the key
    signature). The three sets here disagree on different material, so their
    consensus is markedly steadier than any one of them.

    Empty input defaults to C major.
    """
    histogram = pitch_class_histogram(events)
    if histogram.sum() == 0:
        return KeyEstimate(tonic_pc=0, mode="major", correlation=0.0)

    votes: dict[tuple[int, str], float] = {}
    tally: dict[tuple[int, str], int] = {}

    for major_profile, minor_profile in PROFILE_SETS.values():
        best_key, best_corr = None, -np.inf
        for mode, profile in (("major", major_profile), ("minor", minor_profile)):
            base = np.asarray(profile, dtype=float)
            for tonic in range(12):
                corr = _pearson(histogram, np.roll(base, tonic))
                if corr > best_corr:
                    best_key, best_corr = (tonic, mode), corr
        if best_key is not None:
            tally[best_key] = tally.get(best_key, 0) + 1
            votes[best_key] = votes.get(best_key, 0.0) + best_corr

    # Most votes wins; summed correlation is the tie-break.
    winner = max(tally, key=lambda k: (tally[k], votes[k]))
    tonic, mode = winner
    return KeyEstimate(
        tonic_pc=tonic,
        mode=mode,
        # Report the mean correlation of the sets that chose it, so the
        # confidence figure stays comparable to before.
        correlation=float(votes[winner] / tally[winner]),
    )


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
