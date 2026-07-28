"""Solo piano audio -> readable sheet music.

Pipeline (see module docstrings for details)::

    audio -> transcribe -> [NoteEvent]
          -> beats     -> BeatGrid
          -> quantize  -> [QuantizedNote]
          -> voices    -> staff/voice assignment
          -> spelling  -> key + enharmonic accidentals
          -> notate    -> music21 Score -> MusicXML

Only :mod:`transcribe` and :mod:`evaluate` are fully implemented in the
skeleton; the middle stages are typed stubs to fill in module by module.
"""

from .types import BeatGrid, NoteEvent, QuantizedNote, midi_to_hz

__all__ = ["NoteEvent", "QuantizedNote", "BeatGrid", "midi_to_hz"]
__version__ = "0.1.0"
