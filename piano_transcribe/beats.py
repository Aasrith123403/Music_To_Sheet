"""Audio + note events -> a time-varying beat grid.

The output must be a *sequence* of beat timestamps, not a single BPM. Rubato
and tempo drift make a scalar tempo worthless downstream: quantization snaps
onsets to *these* beat times, whatever their spacing.

Strategy:
  * ``librosa.beat.beat_track`` on the audio gives a robust *tempo hint*.
  * The transcribed note onsets are a far cleaner signal than an audio onset
    envelope, so the actual grid (period + phase) is fitted to them by
    :func:`grid_from_onsets`. Everything downstream snaps to this grid, so its
    phase alignment matters more than anything else in the pipeline.
  * Meter is inferred by testing which bar length best explains where the
    strong (chord/long-note) onsets fall.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .types import BeatGrid, NoteEvent

BPM_MIN = 40.0
BPM_MAX = 208.0
# Tempo-octave prior: the rate listeners tend to tap at. 120 rather than 100 —
# with the centre at 100 anything above about 130 BPM was pulled down an octave
# (a 150 BPM waltz came out as 75), which doubles every notated note value.
PREFERRED_BPM = 120.0


def _onset_weights(onsets: list[float], events: list[NoteEvent] | None,
                   tol: float = 0.03) -> tuple[np.ndarray, np.ndarray]:
    """Collapse near-simultaneous onsets into weighted grid-anchor points.

    Chords and long notes mark beats more strongly than passing notes, so each
    distinct onset time is weighted by how many notes start there and how long
    they last.
    """
    ts = np.asarray(sorted(onsets), dtype=float)
    if ts.size == 0:
        return ts, ts

    # Cluster onsets that fall within `tol` of each other (a chord).
    groups: list[list[float]] = [[float(ts[0])]]
    for t in ts[1:]:
        if t - groups[-1][-1] <= tol:
            groups[-1].append(float(t))
        else:
            groups.append([float(t)])

    times = np.array([float(np.mean(g)) for g in groups])
    weights = np.array([float(len(g)) for g in groups])

    if events:
        # Add a mild bonus for longer notes starting at each anchor.
        durs = {}
        for e in events:
            durs.setdefault(round(e.onset_s, 3), 0.0)
            durs[round(e.onset_s, 3)] = max(durs[round(e.onset_s, 3)], e.duration_s)
        for i, t in enumerate(times):
            best = max((d for o, d in durs.items() if abs(o - t) <= tol), default=0.0)
            weights[i] += min(best, 2.0)

    return times, weights


def grid_from_onsets(
    onsets: list[float],
    bpm_hint: float | None = None,
    events: list[NoteEvent] | None = None,
    beats_per_bar: int | None = None,
) -> BeatGrid:
    """Fit a beat grid (period + phase) to note onset times.

    Uses the standard phase-locked periodicity estimate: for a candidate beat
    period ``p``, ``Z = sum(w * exp(2*pi*i*t/p))`` is large only when the onsets
    cluster at a consistent phase. ``|Z|`` scores the period and ``arg(Z)``
    gives the phase directly, so both fall out of one pass.

    A log-normal prior around :data:`PREFERRED_BPM` (or ``bpm_hint``) breaks the
    tempo-octave ambiguity — otherwise a stream of eighth notes reads as a beat
    at twice the true tempo.
    """
    times, weights = _onset_weights(list(onsets), events)
    if times.size < 2:
        raise ValueError("need at least 2 onsets to fit a beat grid")

    total_w = weights.sum()
    hint = bpm_hint if bpm_hint and BPM_MIN <= bpm_hint <= BPM_MAX else None

    def tempo_prior(bpm: float) -> float:
        """How plausible is ``bpm`` as the beat rate?

        Audio beat trackers reliably find the *pulse* but routinely miss the
        octave (reporting half or double time), so the hint is applied
        octave-invariantly — it constrains the tempo to a power-of-two multiple
        of itself — while a broad prior around :data:`PREFERRED_BPM` picks which
        octave a listener would actually tap. Trusting the hint's octave
        directly just inherits its errors.
        """
        prior = np.exp(-0.5 * (np.log2(bpm / PREFERRED_BPM) / 0.9) ** 2)
        if hint is not None:
            d = np.log2(bpm / hint)
            prior *= np.exp(-0.5 * ((d - np.round(d)) / 0.16) ** 2)
        return float(prior)

    def phasor(p: float) -> complex:
        return np.sum(weights * np.exp(2j * np.pi * times / p))

    # A beat is rarely articulated directly — notes usually subdivide it, and a
    # perfectly even stream of eighths has *no* energy at the quarter-note
    # period. So score a candidate beat by the best-aligning subdivision of it
    # (its "tatum"), and let the tempo prior resolve the octave ambiguity.
    bpms = np.arange(BPM_MIN, BPM_MAX + 0.5, 0.25)
    best = None
    for bpm in bpms:
        p = 60.0 / bpm
        sub_best = max(
            ((np.abs(phasor(p / sub)) / total_w, sub) for sub in (1, 2, 3, 4)),
            key=lambda t: t[0],
        )
        sc = sub_best[0] * tempo_prior(bpm)
        if best is None or sc > best[0]:
            best = (sc, p, sub_best[1])

    _, period, sub = best

    # Phase comes from the tatum (where onsets actually land); the beat is then
    # whichever tatum class carries the most onset weight.
    tatum = period / sub
    t_phase = (np.angle(phasor(tatum)) / (2 * np.pi)) * tatum
    if sub == 1:
        phase = t_phase
    else:
        offsets = [t_phase + k * tatum for k in range(sub)]
        masses = []
        for off in offsets:
            idx = (times - off) / period
            near = np.abs(idx - np.round(idx)) < 0.15
            masses.append(weights[near].sum())
        phase = offsets[int(np.argmax(masses))]

    start = phase % period
    if start > times[0]:
        start -= period * np.ceil((start - times[0]) / period)

    end = float(times[-1]) + period * 4
    n = max(2, int(np.floor((end - start) / period)) + 1)
    beat_times = [float(start + i * period) for i in range(n)]

    bpb = beats_per_bar or _infer_beats_per_bar(times, weights, beat_times)
    return BeatGrid(
        beat_times_s=beat_times,
        downbeats_s=beat_times[::bpb],
        beats_per_bar=bpb,
        beat_unit=4,
    )


# Triple time is only chosen when it beats 4/4 by this margin. Barlines in the
# wrong place make an otherwise-correct transcription look wrong, and duple is
# both far more common and the safer error.
#
# Measured accent contrast (triple minus duple): a real waltz scored +0.039,
# while duple material scored between +0.004 and -0.058. The threshold sits
# between those, but it is calibrated on few examples — triple meter is genuinely
# hard to hear from onset accents alone, so the bias stays towards 4/4.
TRIPLE_METER_MARGIN = 0.025


def _infer_beats_per_bar(times, weights, beat_times) -> int:
    """Pick the bar length whose downbeats best line up with strong onsets.

    Distinguishes triple from duple time only, and is deliberately biased
    towards 4/4: a piece whose accent pattern fits neither (a two-beat ostinato,
    say) scores weakly for both, and picking 3/4 off such a weak signal was
    measured putting barlines through the middle of every bar.
    """
    if len(beat_times) < 4:
        return 4
    period = beat_times[1] - beat_times[0]
    # Beat index (possibly fractional) of every anchor.
    idx = (np.asarray(times) - beat_times[0]) / period
    on_beat = np.abs(idx - np.round(idx)) < 0.25
    if on_beat.sum() < 6:
        return 4
    beat_idx = np.round(idx[on_beat]).astype(int)
    w = np.asarray(weights)[on_beat]

    def contrast(bpb: int) -> float:
        """How much more accent falls on one beat of the bar than by chance."""
        phases = beat_idx % bpb
        totals = np.array([w[phases == ph].sum() for ph in range(bpb)])
        if totals.sum() <= 0:
            return -np.inf
        return float(totals.max() / totals.sum() - 1.0 / bpb)

    duple, triple = contrast(4), contrast(3)
    return 3 if triple > duple + TRIPLE_METER_MARGIN else 4


def track_beats(
    audio_path: str | Path,
    events: list[NoteEvent] | None = None,
    sr: int = 22050,
    beats_per_bar: int | None = None,
) -> BeatGrid:
    """Estimate beat times, downbeats, and a time signature.

    When ``events`` are supplied (the pipeline always does), librosa provides
    the tempo hint and the grid is fitted to the transcribed onsets — markedly
    more accurate than an audio onset envelope for solo instrument recordings.
    Falls back to librosa's own beat frames if that fit isn't possible.
    """
    import librosa

    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    bpm_hint = float(np.atleast_1d(tempo)[0]) if tempo is not None else None

    if events:
        try:
            return grid_from_onsets(
                [e.onset_s for e in events], bpm_hint=bpm_hint,
                events=events, beats_per_bar=beats_per_bar,
            )
        except ValueError:
            pass  # too few onsets — fall through to librosa's grid

    beat_times = [float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]
    if len(beat_times) < 2:
        raise ValueError(
            "beat tracking found fewer than 2 beats; audio may be too short "
            "or silent to quantize against"
        )
    bpb = beats_per_bar or 4
    return BeatGrid(
        beat_times_s=beat_times,
        downbeats_s=beat_times[::bpb],
        beats_per_bar=bpb,
        beat_unit=4,
    )


def seconds_to_beats(grid: BeatGrid, times) -> np.ndarray:
    """Map absolute times (seconds) to fractional beat positions on ``grid``.

    Interior times are linearly interpolated between surrounding beats; times
    before the first or after the last beat are extrapolated using the nearest
    beat spacing (so pickups and trailing notes still land somewhere sensible).

    Returns a float ``ndarray`` of beat positions (beat 0 == first tracked beat).
    """
    bt = np.asarray(grid.beat_times_s, dtype=float)
    t = np.atleast_1d(np.asarray(times, dtype=float))
    n = bt.size
    if n < 2:
        raise ValueError("beat grid needs at least 2 beats")

    idx = np.arange(n, dtype=float)
    out = np.interp(t, bt, idx)  # clamps outside [bt[0], bt[-1]]

    left = t < bt[0]
    if left.any():
        out[left] = (t[left] - bt[0]) / (bt[1] - bt[0])
    right = t > bt[-1]
    if right.any():
        out[right] = (n - 1) + (t[right] - bt[-1]) / (bt[-1] - bt[-2])
    return out
