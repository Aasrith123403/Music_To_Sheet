/**
 * Note-value icons drawn as SVG.
 *
 * The obvious approach — Unicode musical symbols such as U+1D15E (half note)
 * and U+1D160 (eighth note) — fails in practice: those live in the Musical
 * Symbols block, which most system fonts don't cover, so they render as empty
 * boxes. (Clefs and accidentals are the lucky exceptions with wide coverage.)
 * Drawing the note values ourselves is both reliable and sharper at small
 * sizes. The characters are named here rather than written, so the guard in
 * tests/test_frontend_glyphs.py can stay strict.
 *
 * Everything uses `currentColor`, so the icons inherit surrounding text colour.
 */

const STEM_W = 1.6;
const HEAD_RX = 5.4;
const HEAD_RY = 3.9;
const HEAD_TILT = -20; // engraved noteheads sit at a slight angle

function Notehead({ cx, cy, filled }) {
  return (
    <ellipse
      cx={cx}
      cy={cy}
      rx={HEAD_RX}
      ry={HEAD_RY}
      transform={`rotate(${HEAD_TILT} ${cx} ${cy})`}
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={filled ? 0 : 1.9}
    />
  );
}

function Stem({ x, from, to }) {
  return (
    <rect x={x - STEM_W / 2} y={to} width={STEM_W} height={from - to} fill="currentColor" />
  );
}

const box = (w = 24) => ({
  viewBox: `0 0 ${w} 32`,
  width: "1em",
  height: "1.35em",
  style: { overflow: "visible" },
  "aria-hidden": "true",
  focusable: "false",
});

export function QuarterNote() {
  return (
    <svg {...box()}>
      <Notehead cx={8} cy={25} filled />
      <Stem x={13} from={25} to={4} />
    </svg>
  );
}

export function HalfNote() {
  return (
    <svg {...box()}>
      <Notehead cx={8} cy={25} filled={false} />
      <Stem x={13} from={25} to={4} />
    </svg>
  );
}

export function EighthNote() {
  return (
    <svg {...box()}>
      <Notehead cx={8} cy={25} filled />
      <Stem x={13} from={25} to={4} />
      {/* Flag: sweeps out from the stem tip and tucks back in. */}
      <path
        d="M13.6 4.4 C 19.4 7.4, 20.6 12.4, 17.6 17.6 C 19.4 12.2, 17.2 9.2, 13.6 9.9 Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function BeamedNotes() {
  return (
    <svg {...box(34)}>
      <Notehead cx={7} cy={25} filled />
      <Notehead cx={19} cy={25} filled />
      <Stem x={12} from={25} to={6} />
      <Stem x={24} from={25} to={6} />
      {/* The beam that replaces both flags. */}
      <rect x={11.2} y={5} width={13.6} height={3.4} fill="currentColor" />
    </svg>
  );
}
