import { useState } from "react";
import { midiToName, playNote, primeAudio } from "./audio.js";

// Which semitones are black keys, and how the whites lay out in an octave.
const BLACK = new Set([1, 3, 6, 8, 10]);
const WHITE_OFFSETS = [0, 2, 4, 5, 7, 9, 11];

/**
 * A playable piano keyboard.
 *
 * The point for a learner is the three-way link between a *name*, a *sound* and
 * a *position* — so keys are clickable, optionally labelled, and can be driven
 * from outside (e.g. to show where the note in a quiz sits).
 */
export default function Keyboard({
  startOctave = 4,
  octaves = 2,
  showLabels = true,
  highlight = [],
  onKey,
}) {
  const [pressed, setPressed] = useState(null);

  const first = (startOctave + 1) * 12; // MIDI of C in that octave
  const whites = [];
  const blacks = [];

  for (let o = 0; o < octaves; o++) {
    WHITE_OFFSETS.forEach((off, i) => {
      whites.push({ midi: first + o * 12 + off, index: o * 7 + i });
    });
    for (let s = 0; s < 12; s++) {
      if (!BLACK.has(s)) continue;
      // Position each black key between its neighbouring whites.
      const whitesBefore = WHITE_OFFSETS.filter((w) => w < s).length;
      blacks.push({ midi: first + o * 12 + s, index: o * 7 + whitesBefore });
    }
  }

  const total = whites.length;
  const press = (midi) => {
    primeAudio();
    playNote(midi);
    setPressed(midi);
    onKey?.(midi);
    setTimeout(() => setPressed((p) => (p === midi ? null : p)), 260);
  };

  const isLit = (midi) => highlight.includes(midi) || pressed === midi;

  return (
    <div className="keyboard" style={{ "--white-count": total }}>
      <div className="keys-white">
        {whites.map(({ midi }) => (
          <button
            key={midi}
            className={`key white ${isLit(midi) ? "lit" : ""}`}
            onClick={() => press(midi)}
            aria-label={midiToName(midi)}
          >
            {showLabels && <span>{midiToName(midi, { octave: false })}</span>}
          </button>
        ))}
      </div>
      <div className="keys-black">
        {blacks.map(({ midi, index }) => (
          <button
            key={midi}
            className={`key black ${isLit(midi) ? "lit" : ""}`}
            style={{ left: `calc(${index} * (100% / ${total}) - (100% / ${total}) * 0.3)` }}
            onClick={() => press(midi)}
            aria-label={midiToName(midi)}
          />
        ))}
      </div>
    </div>
  );
}
