/**
 * Tiny Web Audio note player.
 *
 * Used wherever a single pitch needs to sound instantly — clicking a notehead,
 * pressing a key on the on-screen keyboard, hearing a quiz answer. Deliberately
 * separate from the score playback (`<audio>` streaming a rendered WAV): that
 * path is for whole pieces, this one has to respond within a few milliseconds
 * of a click and must work offline.
 *
 * The timbre is a small additive stack with a plucked envelope — not a sampled
 * piano, but far less grating than a bare sine and enough to identify a pitch.
 */

let ctx = null;

function context() {
  if (!ctx) {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    ctx = Ctor ? new Ctor() : null;
  }
  // Browsers start the context suspended until a user gesture.
  if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

export function midiToFreq(midi) {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

const NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];

export function midiToName(midi, { octave = true } = {}) {
  const name = NAMES[((midi % 12) + 12) % 12];
  return octave ? `${name}${Math.floor(midi / 12) - 1}` : name;
}

/** Play one pitch. Returns roughly when it finishes (ms). */
export function playNote(midi, { duration = 0.9, gain = 0.22, when = 0 } = {}) {
  const ac = context();
  if (!ac) return duration * 1000;

  const t0 = ac.currentTime + when;
  const freq = midiToFreq(midi);
  const out = ac.createGain();
  out.connect(ac.destination);

  // Amplitude envelope: quick attack, exponential decay (a struck string).
  out.gain.setValueAtTime(0.0001, t0);
  out.gain.exponentialRampToValueAtTime(gain, t0 + 0.012);
  out.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);

  // Partials thin out as they rise, which is roughly what a real string does.
  [[1, 1], [2, 0.32], [3, 0.14], [4, 0.07]].forEach(([mult, amp]) => {
    const osc = ac.createOscillator();
    const g = ac.createGain();
    osc.type = mult === 1 ? "triangle" : "sine";
    osc.frequency.value = freq * mult;
    g.gain.value = amp;
    osc.connect(g);
    g.connect(out);
    osc.start(t0);
    osc.stop(t0 + duration + 0.05);
  });

  return duration * 1000;
}

/** Play several pitches together (a chord). */
export function playChord(midis, opts = {}) {
  // Trim the gain so a thick chord doesn't clip.
  const gain = (opts.gain ?? 0.22) / Math.max(1, Math.sqrt(midis.length));
  midis.forEach((m) => playNote(m, { ...opts, gain }));
}

/** Play pitches one after another. `gap` is seconds between onsets. */
export function playSequence(midis, { gap = 0.55, duration = 0.7, gain = 0.22 } = {}) {
  midis.forEach((m, i) => playNote(m, { duration, gain, when: i * gap }));
  return midis.length * gap * 1000;
}

/** Let a click anywhere unlock audio on browsers that need a gesture. */
export function primeAudio() {
  context();
}
