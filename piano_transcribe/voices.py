"""Quantized events -> staff + voice assignment.

Baseline: split at middle C (MIDI 60) — >= 60 to the treble staff, below to
the bass staff, one voice each.

Better version: cost-based assignment that penalises
  * hand crossings (a bass note above a simultaneous treble note),
  * spans beyond ~an octave and a half within one hand,
  * rapid staff switching for the same melodic line.

The most tractable deep-dive if you want a clean win before tackling
quantization.

STUB — implement in the voicing phase. Mutates ``staff`` / ``voice`` on each
:class:`QuantizedNote` in place (and returns the list for convenience).
"""

from __future__ import annotations

import math

from .types import QuantizedNote

MIDDLE_C = 60


def assign_middle_c_split(notes: list[QuantizedNote]) -> list[QuantizedNote]:
    """Baseline: treble (staff 1) for pitch >= 60, bass (staff 2) below.

    Sets ``staff`` and ``voice`` on each note in place (one voice per staff) and
    returns the same list for chaining.
    """
    for note in notes:
        if note.event.pitch >= MIDDLE_C:
            note.staff, note.voice = 1, 1  # treble, right hand
        else:
            note.staff, note.voice = 2, 1  # bass, left hand
    return notes


# Rough centres of each hand's comfortable range (MIDI): F3 and G4.
BASS_CENTER = 53
TREBLE_CENTER = 67


def assign_cost(
    notes: list[QuantizedNote],
    crossing_penalty: float = 2.0,
    span_penalty: float = 1.0,
    switch_penalty: float = 0.5,
    max_hand_span_semitones: int = 18,
) -> list[QuantizedNote]:
    """Cost-based staff assignment via a two-state (treble/bass) Viterbi.

    Notes are processed in time order. Each note pays an *emission* cost for the
    hand it's assigned to and a *switch* cost when it changes hands from the
    previous note. The optimal path is found by dynamic programming, so a line
    that briefly dips below middle C stays on one staff instead of flip-flopping
    the way a hard middle-C split does.

    Emission cost per hand:
      * a linear pull toward the nearer hand centre (weighted by
        ``crossing_penalty``) — putting a low note in the right hand, or a high
        note in the left, is exactly a hand crossing and costs accordingly;
      * a ``span_penalty`` term once a note sits more than
        ``max_hand_span_semitones`` from that hand's centre.

    Sets ``staff`` (1=treble, 2=bass) and ``voice`` in place; returns the list.
    """
    if not notes:
        return notes

    order = sorted(
        range(len(notes)),
        key=lambda i: (float(notes[i].onset_beats), notes[i].event.pitch),
    )
    pitches = [notes[i].event.pitch for i in order]
    n = len(order)

    def emission(pitch: int, state: int) -> float:
        center = TREBLE_CENTER if state == 0 else BASS_CENTER
        d = abs(pitch - center)
        cost = (crossing_penalty * 0.05) * d  # pull toward the nearer hand
        cost += span_penalty * max(0, d - max_hand_span_semitones) / 12.0
        return cost

    INF = math.inf
    cost = [[INF, INF] for _ in range(n)]
    back = [[0, 0] for _ in range(n)]
    for st in (0, 1):
        cost[0][st] = emission(pitches[0], st)

    for t in range(1, n):
        for st in (0, 1):
            best_prev, best_val = 0, INF
            for pst in (0, 1):
                trans = switch_penalty if pst != st else 0.0
                val = cost[t - 1][pst] + trans
                if val < best_val:
                    best_prev, best_val = pst, val
            cost[t][st] = best_val + emission(pitches[t], st)
            back[t][st] = best_prev

    # Backtrack the cheapest path.
    states = [0] * n
    states[n - 1] = 0 if cost[n - 1][0] <= cost[n - 1][1] else 1
    for t in range(n - 1, 0, -1):
        states[t - 1] = back[t][states[t]]

    for pos, i in enumerate(order):
        notes[i].staff = 1 if states[pos] == 0 else 2
        notes[i].voice = 1
    return notes
