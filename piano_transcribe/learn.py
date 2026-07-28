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
# Flat keys are spelled with flats — B♭ major has a B♭, never an A#.
_FLAT_NAMES = ("C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B")
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


# --- scales and fingering ----------------------------------------------------

MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11, 12)
NATURAL_MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10, 12)
HARMONIC_MINOR_STEPS = (0, 2, 3, 5, 7, 8, 11, 12)
MELODIC_MINOR_STEPS = (0, 2, 3, 5, 7, 9, 11, 12)
BLUES_STEPS = (0, 3, 5, 6, 7, 10, 12)
PENTATONIC_MAJOR_STEPS = (0, 2, 4, 7, 9, 12)
PENTATONIC_MINOR_STEPS = (0, 3, 5, 7, 10, 12)

SCALE_TYPES = {
    "major": ("Major", MAJOR_STEPS),
    "natural_minor": ("Natural minor", NATURAL_MINOR_STEPS),
    "harmonic_minor": ("Harmonic minor", HARMONIC_MINOR_STEPS),
    "melodic_minor": ("Melodic minor (ascending)", MELODIC_MINOR_STEPS),
    "pentatonic_major": ("Major pentatonic", PENTATONIC_MAJOR_STEPS),
    "pentatonic_minor": ("Minor pentatonic", PENTATONIC_MINOR_STEPS),
    "blues": ("Blues", BLUES_STEPS),
}

# Standard one-octave fingerings for the white-key major scales, ascending.
# 1 = thumb … 5 = little finger. These are the classical fingerings taught for
# piano; the thumb-under point is what makes a scale playable at speed, so it
# matters that these are the real ones rather than a generated pattern.
MAJOR_FINGERING = {
    0:  {"right": [1, 2, 3, 1, 2, 3, 4, 5], "left": [5, 4, 3, 2, 1, 3, 2, 1]},   # C
    7:  {"right": [1, 2, 3, 1, 2, 3, 4, 5], "left": [5, 4, 3, 2, 1, 3, 2, 1]},   # G
    2:  {"right": [1, 2, 3, 1, 2, 3, 4, 5], "left": [5, 4, 3, 2, 1, 3, 2, 1]},   # D
    9:  {"right": [1, 2, 3, 1, 2, 3, 4, 5], "left": [5, 4, 3, 2, 1, 3, 2, 1]},   # A
    4:  {"right": [1, 2, 3, 1, 2, 3, 4, 5], "left": [5, 4, 3, 2, 1, 3, 2, 1]},   # E
    11: {"right": [1, 2, 3, 1, 2, 3, 4, 5], "left": [4, 3, 2, 1, 4, 3, 2, 1]},   # B
    5:  {"right": [1, 2, 3, 4, 1, 2, 3, 4], "left": [5, 4, 3, 2, 1, 3, 2, 1]},   # F
}
# The black-key scales start on a different finger so the thumb still lands on
# white keys — the whole point of scale fingering.
BLACK_KEY_FINGERING = {
    6:  {"right": [2, 3, 4, 1, 2, 3, 1, 2], "left": [4, 3, 2, 1, 3, 2, 1, 4]},   # F#
    1:  {"right": [2, 3, 1, 2, 3, 4, 1, 2], "left": [3, 2, 1, 4, 3, 2, 1, 3]},   # C#/Db
    8:  {"right": [3, 4, 1, 2, 3, 1, 2, 3], "left": [3, 2, 1, 4, 3, 2, 1, 3]},   # Ab
    3:  {"right": [3, 1, 2, 3, 4, 1, 2, 3], "left": [3, 2, 1, 4, 3, 2, 1, 3]},   # Eb
    10: {"right": [4, 1, 2, 3, 1, 2, 3, 4], "left": [3, 2, 1, 4, 3, 2, 1, 3]},   # Bb
}


_LETTERS = "CDEFGAB"
_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# Conventional spelling of each tonic. Major keys favour F#/D♭; minor keys
# favour C#/G# — this is why the same key sounds "sharp" or "flat" on paper.
_MAJOR_TONIC = {0: "C", 1: "D♭", 2: "D", 3: "E♭", 4: "E", 5: "F",
                6: "F#", 7: "G", 8: "A♭", 9: "A", 10: "B♭", 11: "B"}
_MINOR_TONIC = {0: "C", 1: "C#", 2: "D", 3: "E♭", 4: "E", 5: "F",
                6: "F#", 7: "G", 8: "G#", 9: "A", 10: "B♭", 11: "B"}


def _accidental(delta: int) -> str:
    return {0: "", 1: "#", 2: "##", -1: "♭", -2: "♭♭"}.get(delta, "")


def _spell_stepwise(tonic_name: str, tonic_pc: int, steps) -> list[str]:
    """Spell a seven-note scale so each degree uses the next letter.

    A scale uses every letter once, in order — which is why F# major's seventh
    degree is E#, not F. Naming it from a pitch-class table instead produces
    two Fs and no E, and teaches the wrong thing.
    """
    start = _LETTERS.index(tonic_name[0])
    names = []
    for i, semis in enumerate(steps):
        letter = _LETTERS[(start + i) % 7]
        target = (tonic_pc + semis) % 12
        delta = (target - _LETTER_PC[letter]) % 12
        if delta > 6:
            delta -= 12
        names.append(letter + _accidental(delta))
    return names


def scale(tonic_pc: int, scale_type: str = "major", octave: int = 4) -> dict:
    """A scale: its pitches, note names, and piano fingering where standard.

    Fingering is only offered for the seven-note scales it's actually defined
    for; a pentatonic or blues scale has no single agreed fingering, so none is
    invented — a wrong fingering is worse than none.
    """
    if scale_type not in SCALE_TYPES:
        raise ValueError(f"Unknown scale type '{scale_type}'.")
    label, steps = SCALE_TYPES[scale_type]
    tonic_pc %= 12
    root = (octave + 1) * 12 + tonic_pc
    pitches = [root + s for s in steps]

    minorish = scale_type in ("natural_minor", "harmonic_minor", "melodic_minor",
                              "pentatonic_minor", "blues")
    tonic_name = (_MINOR_TONIC if minorish else _MAJOR_TONIC)[tonic_pc]

    if len(steps) == 8:
        note_names = _spell_stepwise(tonic_name, tonic_pc, steps)
    else:
        # Pentatonic and blues scales skip letters, so stepwise spelling doesn't
        # apply; flats are the convention for the minor-flavoured ones.
        table = _FLAT_NAMES if minorish or "♭" in tonic_name else _SHARP_NAMES
        note_names = [table[p % 12] for p in pitches]

    fingering = None
    if scale_type == "major":
        fingering = MAJOR_FINGERING.get(tonic_pc) or BLACK_KEY_FINGERING.get(tonic_pc)
    elif scale_type in ("natural_minor", "harmonic_minor", "melodic_minor"):
        # Minor scales reuse the relative major's shape closely enough that the
        # white-key fingering applies; only offer it where that's true.
        fingering = MAJOR_FINGERING.get(tonic_pc)

    return {
        "tonic": tonic_name,
        "type": scale_type,
        "label": f"{tonic_name} {label.lower()}",
        "pitches": pitches,
        "note_names": note_names,
        "intervals": list(steps),
        "fingering": fingering,
        "degrees": len(steps) - 1,
    }


def list_scale_types() -> list[dict]:
    return [{"key": k, "label": v[0]} for k, v in SCALE_TYPES.items()]


# --- practice guidance -------------------------------------------------------

PRACTICE_STEPS = [
    ("Sit properly", "Bench far enough back that your forearms are level with "
     "the keys, wrists neither dropped nor raised. Most early tension comes "
     "from sitting too close."),
    ("Name what you play", "Say the note names aloud as you play them. It is "
     "slow and it feels silly, and it is the fastest route to reading fluently."),
    ("Hands separately first", "Learn each hand on its own until it is easy, "
     "then put them together at half the speed you think you need."),
    ("Slow is the shortcut", "Practise at the speed you can play it correctly. "
     "Speed is a by-product of accuracy, never the other way round."),
    ("Small sections", "Two bars, repeated until secure, beats one pass of the "
     "whole page every time."),
    ("Use the metronome", "Not for the whole session — for the passage that "
     "keeps rushing. Set it slower than feels comfortable."),
]


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
