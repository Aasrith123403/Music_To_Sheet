"""Teaching aids for people learning to read notation.

Three things, all derived from the same music21 machinery the rest of the app
uses:

* :func:`note_quiz` — flashcards. Real engraved staves (rendered from MusicXML
  by the same engine that draws transcriptions), so learners practise on the
  notation they'll actually meet rather than a simplified drawing.
* :func:`score_difficulty` — a readability estimate for a transcribed piece, so
  a beginner can tell whether something is worth attempting yet.
* :func:`key_signature_reference` — the circle of fifths as data.
"""

from __future__ import annotations

import random

# Staff ranges worth drilling: comfortably on/around the staff, few ledger lines.
CLEF_RANGES = {
    "treble": (60, 81),   # C4 .. A5
    "bass": (40, 60),     # E2 .. C4
    "grand": (40, 81),    # both, for players reading two staves
}

_SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_NATURALS = {0: "C", 2: "D", 4: "E", 5: "F", 7: "G", 9: "A", 11: "B"}

CIRCLE_OF_FIFTHS = [
    ("C major", "A minor", 0), ("G major", "E minor", 1), ("D major", "B minor", 2),
    ("A major", "F# minor", 3), ("E major", "C# minor", 4), ("B major", "G# minor", 5),
    ("F# major", "D# minor", 6), ("F major", "D minor", -1), ("B- major", "G minor", -2),
    ("E- major", "C minor", -3), ("A- major", "F minor", -4), ("D- major", "B- minor", -5),
    ("G- major", "E- minor", -6),
]


def _note_musicxml(pitch: int, clef: str) -> str:
    """Engrave a single whole note on an empty staff and return MusicXML."""
    from music21 import clef as m21clef
    from music21 import key, meter, note, stream

    part = stream.Part()
    part.partName = ""
    part.partAbbreviation = ""
    part.insert(0, m21clef.BassClef() if clef == "bass" else m21clef.TrebleClef())
    part.insert(0, key.KeySignature(0))
    part.insert(0, meter.TimeSignature("4/4"))
    n = note.Note(pitch)
    n.quarterLength = 4
    part.insert(0, n)
    part.makeMeasures(inPlace=True)

    score = stream.Score()
    score.insert(0, part)
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    return GeneralObjectExporter().parse(score).decode("utf-8")


def note_quiz(clef: str = "treble", count: int = 10, naturals_only: bool = True,
              seed: int | None = None) -> list[dict]:
    """Generate flashcards: an engraved note plus its answer and choices.

    Args:
        clef: ``treble``, ``bass`` or ``grand``.
        count: How many cards.
        naturals_only: Keep to white keys — accidentals are a separate skill and
            drilling them too early mostly teaches frustration.
        seed: Fixes the sequence, for reproducible tests.

    Each card carries four options (the answer plus near neighbours), because
    plausible distractors are what force real reading rather than guessing.
    """
    rng = random.Random(seed)
    lo, hi = CLEF_RANGES.get(clef, CLEF_RANGES["treble"])

    candidates = [p for p in range(lo, hi + 1)
                  if (p % 12) in _NATURALS or not naturals_only]
    if not candidates:
        candidates = list(range(lo, hi + 1))

    cards = []
    for _ in range(max(1, count)):
        pitch = rng.choice(candidates)
        answer = _NATURALS.get(pitch % 12, _SHARP_NAMES[pitch % 12])
        letters = ["C", "D", "E", "F", "G", "A", "B"]
        idx = letters.index(answer) if answer in letters else 0
        # Neighbours on either side make far better distractors than random
        # letters: confusing D with E is the actual beginner failure mode.
        pool = {letters[(idx + off) % 7] for off in (-2, -1, 1, 2)}
        options = rng.sample(sorted(pool), 3) + [answer]
        rng.shuffle(options)
        card_clef = clef if clef != "grand" else ("bass" if pitch < 60 else "treble")
        cards.append({
            "musicxml": _note_musicxml(pitch, card_clef),
            "answer": answer,
            "octave": pitch // 12 - 1,
            "options": options,
            "clef": card_clef,
        })
    return cards


def score_difficulty(analysis: dict) -> dict:
    """Rate how hard a transcribed piece is to read, 1 (easiest) to 5.

    Combines the things that actually make a score daunting for a learner:
    how many notes go by per second, how many sound at once, how wide the
    reach is, and how many accidentals clutter the page. Deliberately coarse —
    it's a signpost ("is this beyond me yet?"), not a grading system.
    """
    nps = float(analysis.get("notes_per_second") or 0)
    poly = int(analysis.get("max_polyphony") or 1)
    span = int((analysis.get("pitch_range") or {}).get("span_semitones") or 0)
    key_sharps = abs(int(analysis.get("key_signature_sharps") or 0))

    # Weights sum to 5, so the raw score *is* the 1-5 scale once rounded — no
    # offset, which would push ordinary pieces into the top bands.
    score = 0.0
    score += min(nps / 6.0, 1.0) * 2.0       # speed of reading
    score += min(max(poly - 1, 0) / 4.0, 1.0) * 1.5   # simultaneous notes
    score += min(span / 40.0, 1.0) * 1.0     # hand span / ledger lines
    score += min(key_sharps / 5.0, 1.0) * 0.5  # key signature load

    level = int(max(1, min(5, round(score))))
    labels = {
        1: "Beginner", 2: "Easy", 3: "Intermediate",
        4: "Advanced", 5: "Challenging",
    }
    reasons = []
    if nps >= 6:
        reasons.append("notes go by quickly")
    elif nps <= 2:
        reasons.append("a steady, unhurried pace")
    if poly >= 4:
        reasons.append("thick chords")
    elif poly <= 1:
        reasons.append("one note at a time")
    if span >= 30:
        reasons.append("a wide range")
    if key_sharps >= 4:
        reasons.append("a demanding key signature")

    return {"level": level, "label": labels[level], "reasons": reasons}


def key_signature_reference() -> list[dict]:
    """Circle-of-fifths reference data for the learn page."""
    out = []
    for major, minor, sharps in CIRCLE_OF_FIFTHS:
        out.append({
            "major": major.replace("-", "♭"),
            "minor": minor.replace("-", "♭"),
            "sharps": sharps,
            "accidentals": (
                "none" if sharps == 0
                else f"{abs(sharps)} {'sharp' if sharps > 0 else 'flat'}"
                     f"{'s' if abs(sharps) > 1 else ''}"
            ),
        })
    return out
