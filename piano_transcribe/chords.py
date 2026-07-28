"""Chord construction, identification and progressions.

Three directions, all built on interval formulas rather than a lookup table of
named chords, so voicings and inversions fall out of the same code:

* **Build** — root + quality (+ inversion) -> pitches and engraved notation.
* **Identify** — an arbitrary set of pitches -> the chord's name. This is what
  turns "press some keys and see what you invented" into a teaching moment.
* **Suggest** — diatonic chords and common progressions in a key.
"""

from __future__ import annotations

from dataclasses import dataclass

NOTE_NAMES_SHARP = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
NOTE_NAMES_FLAT = ("C", "D-", "D", "E-", "E", "F", "G-", "G", "A-", "A", "B-", "B")

# Semitones above the root. Ordered roughly simple -> complex, which also makes
# identification prefer the plainest reading of an ambiguous set.
QUALITIES: dict[str, tuple[str, tuple[int, ...]]] = {
    "maj":     ("major",            (0, 4, 7)),
    "min":     ("minor",            (0, 3, 7)),
    "dim":     ("diminished",       (0, 3, 6)),
    "aug":     ("augmented",        (0, 4, 8)),
    "sus2":    ("suspended 2nd",    (0, 2, 7)),
    "sus4":    ("suspended 4th",    (0, 5, 7)),
    "maj7":    ("major 7th",        (0, 4, 7, 11)),
    "7":       ("dominant 7th",     (0, 4, 7, 10)),
    "min7":    ("minor 7th",        (0, 3, 7, 10)),
    "min7b5":  ("half-diminished",  (0, 3, 6, 10)),
    "dim7":    ("diminished 7th",   (0, 3, 6, 9)),
    "minmaj7": ("minor-major 7th",  (0, 3, 7, 11)),
    "6":       ("major 6th",        (0, 4, 7, 9)),
    "min6":    ("minor 6th",        (0, 3, 7, 9)),
    "9":       ("dominant 9th",     (0, 4, 7, 10, 14)),
    "maj9":    ("major 9th",        (0, 4, 7, 11, 14)),
    "min9":    ("minor 9th",        (0, 3, 7, 10, 14)),
    "add9":    ("added 9th",        (0, 4, 7, 14)),
}

# Scale-degree chords for major and minor keys, with the roman numerals a
# learner will meet in any theory book.
MAJOR_DIATONIC = [
    (0, "maj", "I"), (2, "min", "ii"), (4, "min", "iii"), (5, "maj", "IV"),
    (7, "maj", "V"), (9, "min", "vi"), (11, "dim", "vii°"),
]
MINOR_DIATONIC = [
    (0, "min", "i"), (2, "dim", "ii°"), (3, "maj", "III"), (5, "min", "iv"),
    (7, "min", "v"), (8, "maj", "VI"), (10, "maj", "VII"),
]

PROGRESSIONS = [
    ("I–V–vi–IV", [0, 4, 5, 3], "major", "The four chords behind a great deal of pop."),
    ("I–vi–IV–V", [0, 5, 3, 4], "major", "The 1950s doo-wop turnaround."),
    ("ii–V–I", [1, 4, 0], "major", "The backbone of jazz harmony."),
    ("I–IV–V–I", [0, 3, 4, 0], "major", "The plainest cadence in tonal music."),
    ("vi–IV–I–V", [5, 3, 0, 4], "major", "The same four chords, started elsewhere."),
    ("i–VI–III–VII", [0, 5, 2, 6], "minor", "Brooding, and very common in film music."),
    ("i–iv–v–i", [0, 3, 4, 0], "minor", "The minor-key cadence."),
    ("i–VII–VI–V", [0, 6, 5, 4], "minor", "The descending 'Andalusian' line."),
]


@dataclass
class Chord:
    root_pc: int
    quality: str
    inversion: int
    pitches: list[int]      # MIDI, in sounding order
    name: str               # e.g. "Cmaj7"
    full_name: str          # e.g. "C major 7th"
    intervals: list[int]

    def as_dict(self) -> dict:
        return {
            "root": NOTE_NAMES_SHARP[self.root_pc],
            "quality": self.quality,
            "inversion": self.inversion,
            "pitches": self.pitches,
            "name": self.name,
            "full_name": self.full_name,
            "intervals": self.intervals,
            "note_names": [NOTE_NAMES_SHARP[p % 12] for p in self.pitches],
        }


def build_chord(root_pc: int, quality: str = "maj", octave: int = 4,
                inversion: int = 0) -> Chord:
    """Build a chord from a root pitch class and a quality name."""
    if quality not in QUALITIES:
        raise ValueError(f"Unknown chord quality '{quality}'.")
    full, intervals = QUALITIES[quality]
    root_midi = (octave + 1) * 12 + (root_pc % 12)
    pitches = [root_midi + i for i in intervals]

    # Invert by lifting the lowest notes an octave, which is what a player does.
    inversion = inversion % len(pitches)
    for _ in range(inversion):
        pitches.append(pitches.pop(0) + 12)

    root_name = NOTE_NAMES_SHARP[root_pc % 12]
    return Chord(
        root_pc=root_pc % 12,
        quality=quality,
        inversion=inversion,
        pitches=pitches,
        name=f"{root_name}{'' if quality == 'maj' else quality}",
        full_name=f"{root_name} {full}",
        intervals=list(intervals),
    )


def identify_chord(pitches: list[int]) -> dict:
    """Name an arbitrary set of pitches.

    Tries every pitch present as a candidate root and keeps the reading whose
    interval set matches a known quality exactly; failing that, reports the
    closest match so experimenting never produces a dead end. Inversions are
    detected by comparing against the lowest sounding note.
    """
    if not pitches:
        return {"name": None, "full_name": None, "notes": []}

    unique_pcs = sorted({p % 12 for p in pitches})
    bass_pc = min(pitches) % 12
    notes = [NOTE_NAMES_SHARP[p % 12] for p in sorted(set(pitches))]

    if len(unique_pcs) == 1:
        name = NOTE_NAMES_SHARP[unique_pcs[0]]
        return {"name": name, "full_name": f"{name} (single note)", "notes": notes,
                "root": name, "inversion": 0, "exact": True}

    if len(unique_pcs) == 2:
        low, high = unique_pcs
        semis = (high - low) % 12
        interval_names = {
            1: "minor 2nd", 2: "major 2nd", 3: "minor 3rd", 4: "major 3rd",
            5: "perfect 4th", 6: "tritone", 7: "perfect 5th", 8: "minor 6th",
            9: "major 6th", 10: "minor 7th", 11: "major 7th",
        }
        label = interval_names.get(semis, "interval")
        return {"name": f"{NOTE_NAMES_SHARP[low]}+{NOTE_NAMES_SHARP[high]}",
                "full_name": f"{label} (two notes — not yet a chord)",
                "notes": notes, "root": NOTE_NAMES_SHARP[low],
                "inversion": 0, "exact": False}

    # Try the bass note as the root first. Several chords share a pitch-class
    # set — A-C-E-G is both Am7 and C6 — and what decides it for a listener is
    # which note is underneath. Falling back to ascending order keeps inversions
    # working, since E-G-C spells nothing rooted on E and resolves to C/E.
    best = None
    for root in [bass_pc] + [pc for pc in unique_pcs if pc != bass_pc]:
        rel = sorted({(pc - root) % 12 for pc in unique_pcs})
        for quality, (full, intervals) in QUALITIES.items():
            target = sorted({i % 12 for i in intervals})
            if rel == target:
                inversion = _inversion_for(root, bass_pc, intervals)
                root_name = NOTE_NAMES_SHARP[root]
                return {
                    "name": f"{root_name}{'' if quality == 'maj' else quality}"
                            + (f"/{NOTE_NAMES_SHARP[bass_pc]}" if inversion else ""),
                    "full_name": f"{root_name} {full}"
                                 + (f", inversion {inversion}" if inversion else ""),
                    "root": root_name, "quality": quality, "inversion": inversion,
                    "notes": notes, "exact": True,
                }
            # Track the nearest miss so an unusual set still gets a suggestion.
            overlap = len(set(rel) & set(target))
            distance = len(set(rel) ^ set(target))
            if best is None or (overlap, -distance) > (best[0], -best[1]):
                best = (overlap, distance, root, quality, full)

    if best:
        _, _, root, quality, full = best
        root_name = NOTE_NAMES_SHARP[root]
        return {
            "name": f"{root_name}{quality}?",
            "full_name": f"closest to {root_name} {full}",
            "root": root_name, "quality": quality, "inversion": 0,
            "notes": notes, "exact": False,
        }
    return {"name": None, "full_name": "unrecognised", "notes": notes, "exact": False}


def _inversion_for(root_pc: int, bass_pc: int, intervals: tuple[int, ...]) -> int:
    """Which inversion puts ``bass_pc`` at the bottom?"""
    for idx, semis in enumerate(intervals):
        if (root_pc + semis) % 12 == bass_pc % 12:
            return idx
    return 0


def diatonic_chords(tonic_pc: int, mode: str = "major", octave: int = 4) -> list[dict]:
    """The seven chords that belong to a key, with roman numerals."""
    table = MAJOR_DIATONIC if mode == "major" else MINOR_DIATONIC
    out = []
    for degree, quality, numeral in table:
        chord = build_chord((tonic_pc + degree) % 12, quality, octave=octave)
        entry = chord.as_dict()
        entry["numeral"] = numeral
        entry["degree"] = degree
        out.append(entry)
    return out


def progressions(tonic_pc: int, mode: str = "major", octave: int = 4) -> list[dict]:
    """Common progressions in a key, ready to play."""
    scale = diatonic_chords(tonic_pc, mode, octave=octave)
    out = []
    for name, degrees, prog_mode, blurb in PROGRESSIONS:
        if prog_mode != mode:
            continue
        chords = [scale[d] for d in degrees]
        out.append({
            "name": name,
            "description": blurb,
            "chords": chords,
            "numerals": [c["numeral"] for c in chords],
        })
    return out


def chord_musicxml(pitches: list[int], label: str = "") -> str:
    """Engrave a chord on a grand staff so it can be rendered like any score."""
    from music21 import chord as m21chord
    from music21 import clef, key, meter, stream
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    treble = stream.PartStaff(id="RH")
    bass = stream.PartStaff(id="LH")
    for part, cl in ((treble, clef.TrebleClef()), (bass, clef.BassClef())):
        part.partName = ""
        part.partAbbreviation = ""
        part.insert(0, cl)
        part.insert(0, key.KeySignature(0))
        part.insert(0, meter.TimeSignature("4/4"))

    upper = [p for p in pitches if p >= 60]
    lower = [p for p in pitches if p < 60]
    for part, group in ((treble, upper), (bass, lower)):
        if group:
            c = m21chord.Chord(sorted(group))
            c.quarterLength = 4
            if label and part is treble:
                c.addLyric(label)
            part.insert(0, c)
        else:
            from music21 import note as m21note

            r = m21note.Rest()
            r.quarterLength = 4
            part.insert(0, r)
        part.makeMeasures(inPlace=True)

    score = stream.Score()
    score.insert(0, treble)
    score.insert(0, bass)
    from music21 import layout

    score.insert(0, layout.StaffGroup([treble, bass], symbol="brace", barTogether=True))
    return GeneralObjectExporter().parse(score).decode("utf-8")
