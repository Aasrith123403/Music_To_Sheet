"""Shared data types that flow between pipeline stages.

``NoteEvent`` is *the* interface between transcription and everything
downstream. Keep it stable: the transcription model can be swapped freely as
long as it emits ``list[NoteEvent]``.

The later stages enrich notes without discarding the raw timing, so
``QuantizedNote`` and ``VoicedNote`` wrap a ``NoteEvent`` rather than replace
it. That lets ``evaluate.py`` always fall back to the original onset/offset in
seconds no matter how far down the pipeline a note has travelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction


def midi_to_hz(pitch: int) -> float:
    """Convert a MIDI note number to frequency in Hz (A4 = 69 = 440 Hz).

    mir_eval's transcription metrics expect pitches in Hz, so this is the
    canonical conversion used by :mod:`piano_transcribe.evaluate`.
    """
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


@dataclass
class NoteEvent:
    """A single sounded note, in absolute time.

    This is the raw output of transcription and the input to every downstream
    stage. All timing is in seconds; pitch is an integer MIDI note number.

    Attributes:
        pitch: MIDI note number (21=A0 .. 108=C8 for a standard piano).
        onset_s: Note start time, in seconds from the beginning of the audio.
        offset_s: Note end time, in seconds. Must be >= ``onset_s``.
        velocity: MIDI-style loudness, 1-127. Transcribers that only expose an
            amplitude should scale it into this range.
    """

    pitch: int
    onset_s: float
    offset_s: float
    velocity: int = 64

    def __post_init__(self) -> None:
        if self.offset_s < self.onset_s:
            raise ValueError(
                f"offset_s ({self.offset_s}) precedes onset_s ({self.onset_s})"
            )

    @property
    def duration_s(self) -> float:
        return self.offset_s - self.onset_s

    @property
    def frequency_hz(self) -> float:
        return midi_to_hz(self.pitch)


@dataclass
class QuantizedNote:
    """A note snapped to the metrical grid by :mod:`piano_transcribe.quantize`.

    Attributes:
        event: The original, un-quantized :class:`NoteEvent`.
        onset_beats: Metrical onset position, in quarter-note beats from the
            start of the piece (e.g. 4.5 == the "and" of beat 1 in measure 2 in
            4/4). Kept as an exact ``Fraction`` to survive tuplet math.
        duration_beats: Notated duration in quarter-note beats, also exact.
        voice: Voice index within a staff (filled later by voices.py; -1 = unset).
        staff: 1 = treble, 2 = bass (filled later by voices.py; 0 = unset).
    """

    event: NoteEvent
    onset_beats: Fraction
    duration_beats: Fraction
    voice: int = -1
    staff: int = 0


@dataclass
class BeatGrid:
    """A time-varying beat grid, the output of :mod:`piano_transcribe.beats`.

    A *sequence* of beat times, not a single BPM — rubato and tempo changes make
    a scalar tempo useless for quantization.

    Attributes:
        beat_times_s: Ascending beat onset times in seconds.
        downbeats_s: Subset of ``beat_times_s`` that fall on measure starts.
        beats_per_bar: Numerator of the time signature (e.g. 4 for 4/4).
        beat_unit: Denominator of the time signature (e.g. 4 == quarter note).
    """

    beat_times_s: list[float]
    downbeats_s: list[float] = field(default_factory=list)
    beats_per_bar: int = 4
    beat_unit: int = 4

    @property
    def time_signature(self) -> str:
        return f"{self.beats_per_bar}/{self.beat_unit}"

    @property
    def tempo_bpm(self) -> float | None:
        """Representative tempo, from the median beat interval.

        Median rather than mean so a single mis-tracked beat (or a fermata)
        doesn't skew it. ``None`` when there aren't enough beats to tell.
        """
        times = self.beat_times_s
        if len(times) < 2:
            return None
        diffs = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
        if not diffs:
            return None
        median = diffs[len(diffs) // 2]
        return 60.0 / median if median > 0 else None
