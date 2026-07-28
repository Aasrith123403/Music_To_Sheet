"""Instrument specifications.

The pipeline stays single-instrument (no source separation): one recording,
one instrument, chosen up front. The instrument spec controls three things the
notation needs to be *correct* rather than just piano-shaped:

  * **pitch range** — band-limits transcription (basic-pitch min/max frequency),
    which trims spurious out-of-range notes;
  * **staff layout** — piano gets a two-staff grand staff; everything else is a
    single staff with the right clef;
  * **transposition** — for transposing instruments (Bb clarinet, Eb alto sax,
    Bb trumpet) the *written* pitch differs from the *sounding* pitch, so the
    displayed notes and key signature are shifted by ``transposition``
    semitones (written = sounding + transposition).
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import midi_to_hz


@dataclass(frozen=True)
class Instrument:
    """How to transcribe and notate one instrument.

    Attributes:
        key: Stable identifier used by the API/UI (e.g. ``"alto_sax"``).
        display_name: Human label for the dropdown.
        midi_min / midi_max: Sounding pitch range, MIDI note numbers.
        notation: ``"grand"`` (two staves) or ``"single"`` (one staff).
        clef: music21 clef name — see :data:`_CLEFS`.
        transposition: Semitones added to a *sounding* pitch to get the
            *written* pitch (0 for concert-pitch instruments).
    """

    key: str
    display_name: str
    midi_min: int
    midi_max: int
    notation: str
    clef: str
    transposition: int = 0

    @property
    def freq_min(self) -> float:
        return midi_to_hz(self.midi_min)

    @property
    def freq_max(self) -> float:
        return midi_to_hz(self.midi_max)


# Supported clef names -> music21 clef classes (resolved lazily in notate.py to
# avoid importing music21 here).
_CLEFS = {
    "treble": "TrebleClef",
    "bass": "BassClef",
    "alto": "AltoClef",
    "tenor": "TenorClef",
    "treble8vb": "Treble8vbClef",  # guitar, tenor voice: sounds an octave down
    "bass8vb": "Bass8vbClef",      # bass guitar, contrabass
}


_REGISTRY: dict[str, Instrument] = {
    inst.key: inst
    for inst in [
        Instrument("piano", "Piano", 21, 108, "grand", "treble"),
        Instrument("guitar", "Guitar", 40, 88, "single", "treble8vb"),
        Instrument("bass_guitar", "Bass Guitar", 28, 67, "single", "bass8vb"),
        Instrument("violin", "Violin", 55, 103, "single", "treble"),
        Instrument("viola", "Viola", 48, 91, "single", "alto"),
        Instrument("cello", "Cello", 36, 84, "single", "bass"),
        Instrument("flute", "Flute", 60, 96, "single", "treble"),
        Instrument("clarinet", "Clarinet (B♭)", 50, 94, "single", "treble", transposition=2),
        Instrument("alto_sax", "Alto Sax (E♭)", 49, 84, "single", "treble", transposition=9),
        Instrument("trumpet", "Trumpet (B♭)", 52, 82, "single", "treble", transposition=2),
        Instrument("voice", "Voice", 48, 84, "single", "treble"),
    ]
}

DEFAULT_INSTRUMENT = "piano"


def get_instrument(key: str | None) -> Instrument:
    """Look up an instrument, falling back to piano for unknown/None keys."""
    return _REGISTRY.get(key or DEFAULT_INSTRUMENT, _REGISTRY[DEFAULT_INSTRUMENT])


def list_instruments() -> list[dict]:
    """Registry as JSON-friendly dicts for the API/UI dropdown (piano first)."""
    return [
        {"key": i.key, "display_name": i.display_name, "notation": i.notation}
        for i in _REGISTRY.values()
    ]


def music21_clef_name(clef: str) -> str:
    """Map a spec clef name to its music21 class name."""
    return _CLEFS.get(clef, "TrebleClef")
