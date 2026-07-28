"""Run the pipeline over a MAESTRO subset and print/write a metrics table.

Usage:
    python -m cli.run_eval --maestro /path/to/maestro-v3.0.0 --limit 10 \
        --out data/eval.csv [--full]

MAESTRO ships a ``maestro-*.csv`` index plus aligned ``(audio.wav,
ground_truth.midi)`` pairs. For each piece this:

  * loads ground-truth notes from the MIDI                 (the *reference*),
  * runs transcription on the audio                        (the *estimate*),
  * scores tier-1 note accuracy (onset / onset+offset F1).

With ``--full`` it also beats + quantizes both note streams on the same grid to
report tier-2 rhythmic accuracy and tier-3 notation complexity — the full
readability picture, at the cost of running beat tracking and quantization per
piece.
"""

from __future__ import annotations

import argparse
import csv as csvmod
from pathlib import Path

from piano_transcribe import beats, notate, quantize, spelling, voices
from piano_transcribe.evaluate import (
    evaluate_dataset,
    evaluate_transcription,
    notation_complexity,
    rhythmic_accuracy,
)
from piano_transcribe.transcribe import Transcriber, transcribe
from piano_transcribe.types import NoteEvent


def load_midi_notes(midi_path: str | Path) -> list[NoteEvent]:
    """Load a MIDI file into ``NoteEvent``s (seconds), sorted by onset.

    Drum tracks are skipped; all melodic instruments are merged (MAESTRO's
    ground truth is a single piano part, but merging is harmless and general).
    """
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(str(midi_path))
    notes: list[NoteEvent] = []
    for instrument in pm.instruments:
        if instrument.is_drum:
            continue
        for n in instrument.notes:
            notes.append(
                NoteEvent(pitch=n.pitch, onset_s=float(n.start),
                          offset_s=float(n.end), velocity=int(n.velocity))
            )
    notes.sort(key=lambda e: (e.onset_s, e.pitch))
    return notes


def _index_rows(maestro_root: Path) -> list[tuple[str, Path, Path]]:
    """Return ``(name, audio_path, midi_path)`` triples from the MAESTRO csv."""
    csvs = sorted(maestro_root.glob("maestro-*.csv")) or sorted(maestro_root.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"No MAESTRO index csv under {maestro_root}")

    rows: list[tuple[str, Path, Path]] = []
    with csvs[0].open() as fh:
        for row in csvmod.DictReader(fh):
            audio = maestro_root / row["audio_filename"]
            midi = maestro_root / row["midi_filename"]
            name = Path(row["audio_filename"]).stem
            rows.append((name, audio, midi))
    return rows


def load_maestro_pairs(
    maestro_root: Path,
    limit: int | None = None,
    transcriber: Transcriber | None = None,
) -> list[tuple[str, list[NoteEvent], list[NoteEvent]]]:
    """Build ``(name, reference, estimate)`` triples from a MAESTRO subset.

    Reference = ground-truth MIDI notes; estimate = transcription of the audio.
    """
    triples = _index_rows(maestro_root)
    if limit is not None:
        triples = triples[:limit]

    pairs: list[tuple[str, list[NoteEvent], list[NoteEvent]]] = []
    for name, audio_path, midi_path in triples:
        reference = load_midi_notes(midi_path)
        estimate = transcribe(audio_path, transcriber=transcriber)
        pairs.append((name, reference, estimate))
    return pairs


def _full_metrics_row(
    name: str, audio_path: Path, reference: list[NoteEvent], estimate: list[NoteEvent]
) -> dict:
    """Tier 1 + 2 + 3 for one piece (quantizes both streams on a shared grid)."""
    tier1 = evaluate_transcription(reference, estimate)
    grid = beats.track_beats(audio_path, estimate)
    ref_q = quantize.quantize_nearest(reference, grid)
    est_q = quantize.quantize_nearest(estimate, grid)
    rhythm = rhythmic_accuracy(ref_q, est_q)

    voices.assign_middle_c_split(est_q)
    key = spelling.estimate_key(estimate)
    names = spelling.spell_notes(estimate, key)
    score = notate.build_score(est_q, grid, key, note_names=names, title=name)
    cx = notation_complexity(score)

    return {
        "piece": name,
        **tier1.as_row(),
        "rhythmic_accuracy": round(rhythm, 4),
        "tuplets_per_measure": round(cx.tuplets / cx.measures if cx.measures else 0, 4),
        "ties_per_measure": round(cx.ties_across_barlines / cx.measures if cx.measures else 0, 4),
        "accidentals_per_measure": round(cx.accidentals_per_measure, 4),
    }


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("(no rows)")
        return
    headers = list(rows[0].keys())
    widths = {h: max(len(h), *(len(str(r.get(h, ""))) for r in rows)) for h in headers}
    line = "  ".join(h.ljust(widths[h]) for h in headers)
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(r.get(h, "")).ljust(widths[h]) for h in headers))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate on a MAESTRO subset.")
    parser.add_argument("--maestro", type=Path, required=True,
                        help="Path to the MAESTRO dataset root.")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max number of pieces to score.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Optional CSV output path.")
    parser.add_argument("--full", action="store_true",
                        help="Also compute tier-2 rhythm + tier-3 complexity.")
    args = parser.parse_args()

    if args.full:
        triples = _index_rows(args.maestro)[: args.limit]
        rows = [
            _full_metrics_row(name, audio, load_midi_notes(midi), transcribe(audio))
            for name, audio, midi in triples
        ]
        if args.out:
            _write_csv(rows, args.out)
    else:
        pairs = load_maestro_pairs(args.maestro, limit=args.limit)
        rows = evaluate_dataset(pairs, out_csv=args.out)

    _print_table(rows)
    if args.out:
        print(f"\nWrote {args.out}")


def _write_csv(rows: list[dict], out_csv: Path) -> None:
    if not rows:
        return
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        writer = csvmod.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
