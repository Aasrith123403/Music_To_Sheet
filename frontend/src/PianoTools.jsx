import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import Keyboard from "./Keyboard.jsx";
import { midiToName, playChord, playNote, playSequence, primeAudio } from "./audio.js";

/**
 * Practice tools for learning the piano itself, as opposed to reading notation:
 * a metronome, scales with real fingering, and chord ear-training.
 */

/* ------------------------------------------------------------------ metronome */

export function Metronome() {
  const [bpm, setBpm] = useState(80);
  const [beatsPerBar, setBeatsPerBar] = useState(4);
  const [running, setRunning] = useState(false);
  const [beat, setBeat] = useState(0);
  const timer = useRef(null);
  const beatRef = useRef(0);

  useEffect(() => {
    if (!running) {
      clearInterval(timer.current);
      return undefined;
    }
    primeAudio();
    beatRef.current = 0;
    const tick = () => {
      const isDownbeat = beatRef.current % beatsPerBar === 0;
      // A higher, louder click on beat one is what makes the bar audible.
      playNote(isDownbeat ? 96 : 84, { duration: 0.06, gain: isDownbeat ? 0.5 : 0.28 });
      setBeat(beatRef.current % beatsPerBar);
      beatRef.current += 1;
    };
    tick();
    timer.current = setInterval(tick, (60 / bpm) * 1000);
    return () => clearInterval(timer.current);
  }, [running, bpm, beatsPerBar]);

  return (
    <div className="card learn-card">
      <div className="learn-head">
        <h2>Metronome</h2>
        <div className="clef-picker">
          {[2, 3, 4, 6].map((n) => (
            <button
              key={n}
              className={`tab ${beatsPerBar === n ? "active" : ""}`}
              onClick={() => setBeatsPerBar(n)}
            >
              {n}/4
            </button>
          ))}
        </div>
      </div>
      <p className="footnote">
        Use it on the passage that keeps rushing, not the whole session. Set it
        slower than feels comfortable — speed is a by-product of accuracy.
      </p>

      <div className="metronome">
        <div className="beat-lights">
          {Array.from({ length: beatsPerBar }, (_, i) => (
            <span
              key={i}
              className={`beat-light ${running && beat === i ? "on" : ""} ${i === 0 ? "downbeat" : ""}`}
            />
          ))}
        </div>
        <div className="bpm-row">
          <button className="ghost-btn" onClick={() => setBpm((b) => Math.max(30, b - 5))}>
            −
          </button>
          <div className="bpm-display">
            <span className="bpm-number">{bpm}</span>
            <span className="bpm-label">BPM</span>
          </div>
          <button className="ghost-btn" onClick={() => setBpm((b) => Math.min(240, b + 5))}>
            +
          </button>
        </div>
        <input
          type="range"
          min="30"
          max="240"
          value={bpm}
          onChange={(e) => setBpm(Number(e.target.value))}
          className="bpm-slider"
        />
        <button className="primary full" onClick={() => setRunning((r) => !r)}>
          {running ? "Stop" : "Start"}
        </button>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------- scales */

export function ScaleTrainer() {
  const [types, setTypes] = useState([]);
  const [tonic, setTonic] = useState(0);
  const [type, setType] = useState("major");
  const [hand, setHand] = useState("right");
  const [scale, setScale] = useState(null);
  const [step, setStep] = useState(-1);

  useEffect(() => {
    api.scaleTypes().then((d) => setTypes(d.types)).catch(() => {});
  }, []);

  useEffect(() => {
    api.scale(tonic, type).then(setScale).catch(() => {});
  }, [tonic, type]);

  function playScale() {
    if (!scale) return;
    primeAudio();
    playSequence(scale.pitches, { gap: 0.34, duration: 0.5 });
    // Walk the highlight along with the notes so fingering lines up visually.
    scale.pitches.forEach((_, i) => {
      setTimeout(() => setStep(i), i * 340);
    });
    setTimeout(() => setStep(-1), scale.pitches.length * 340 + 200);
  }

  const fingers = scale?.fingering?.[hand];

  return (
    <div className="card learn-card">
      <div className="learn-head">
        <h2>Scales</h2>
        <div className="chord-controls compact">
          <select value={tonic} onChange={(e) => setTonic(Number(e.target.value))}>
            {["C", "C#/D♭", "D", "D#/E♭", "E", "F", "F#/G♭", "G", "G#/A♭", "A", "A#/B♭", "B"].map(
              (n, i) => (
                <option key={n} value={i}>{n}</option>
              )
            )}
          </select>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {types.map((t) => (
              <option key={t.key} value={t.key}>{t.label}</option>
            ))}
          </select>
        </div>
      </div>

      {scale && (
        <>
          <div className="chord-headline">
            <span className="chord-name">{scale.label}</span>
          </div>

          <div className="scale-degrees">
            {scale.note_names.map((n, i) => (
              <div className={`scale-degree ${step === i ? "on" : ""}`} key={`${n}-${i}`}>
                <span className="deg-note">{n}</span>
                {fingers && <span className="deg-finger">{fingers[i]}</span>}
              </div>
            ))}
          </div>

          {fingers ? (
            <p className="footnote">
              The numbers are fingers — 1 is the thumb, 5 the little finger.
              Watch where the thumb tucks under; that's what lets a scale run
              smoothly instead of stopping at every five notes.
            </p>
          ) : (
            <p className="footnote">
              This scale has no single standard fingering, so none is shown —
              a made-up one would be worse than none.
            </p>
          )}

          <div className="scale-actions">
            <div className="clef-picker">
              {["right", "left"].map((h) => (
                <button
                  key={h}
                  className={`tab ${hand === h ? "active" : ""}`}
                  onClick={() => setHand(h)}
                  disabled={!scale.fingering}
                >
                  {h} hand
                </button>
              ))}
            </div>
            <button className="primary" onClick={playScale}>♪ Play scale</button>
          </div>

          <Keyboard
            startOctave={4}
            octaves={2}
            showLabels={false}
            highlight={step >= 0 ? [scale.pitches[step]] : scale.pitches}
          />
        </>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- chord ears */

const EAR_QUALITIES = [
  ["maj", "Major"],
  ["min", "Minor"],
  ["dim", "Diminished"],
  ["aug", "Augmented"],
  ["7", "Dominant 7th"],
  ["maj7", "Major 7th"],
  ["min7", "Minor 7th"],
];

export function ChordEar() {
  const [level, setLevel] = useState(2);
  const [current, setCurrent] = useState(null);
  const [picked, setPicked] = useState(null);
  const [score, setScore] = useState({ right: 0, total: 0 });

  const choices = EAR_QUALITIES.slice(0, level === 1 ? 2 : level === 2 ? 4 : 7);

  async function newQuestion() {
    const [quality, label] = choices[Math.floor(Math.random() * choices.length)];
    const root = 55 + Math.floor(Math.random() * 10);
    try {
      const chord = await api.buildChord(root % 12, quality, 0, 4);
      setCurrent({ quality, label, pitches: chord.pitches });
      setPicked(null);
      primeAudio();
      playChord(chord.pitches, { duration: 1.4 });
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    newQuestion();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [level]);

  function answer(label) {
    if (picked || !current) return;
    setPicked(label);
    setScore((s) => ({
      right: s.right + (label === current.label ? 1 : 0),
      total: s.total + 1,
    }));
  }

  return (
    <div className="card learn-card">
      <div className="learn-head">
        <h2>Hearing chords</h2>
        <div className="clef-picker">
          {[1, 2, 3].map((n) => (
            <button
              key={n}
              className={`tab ${level === n ? "active" : ""}`}
              onClick={() => setLevel(n)}
            >
              {n === 1 ? "Easy" : n === 2 ? "Medium" : "All"}
            </button>
          ))}
        </div>
      </div>
      <p className="footnote">
        Major and minor first — that difference is the one your ear needs most.
        Sevenths and altered chords once those are automatic.
      </p>

      <div className="ear-controls">
        <button
          className="primary"
          onClick={() => {
            if (!current) return;
            primeAudio();
            playChord(current.pitches, { duration: 1.4 });
          }}
        >
          ♪ Play again
        </button>
        <span className="quiz-progress">{score.right}/{score.total} correct</span>
      </div>

      <div className="options interval-options">
        {choices.map(([, label]) => {
          const cls = picked
            ? label === current?.label
              ? "option correct"
              : label === picked
              ? "option wrong"
              : "option"
            : "option";
          return (
            <button key={label} className={cls} onClick={() => answer(label)}>
              {label}
            </button>
          );
        })}
      </div>

      {picked && current && (
        <div className="quiz-feedback">
          <span>
            {picked === current.label
              ? "Correct."
              : `That was ${current.label.toLowerCase()}.`}{" "}
            <em className="heard">{current.pitches.map((p) => midiToName(p)).join(" ")}</em>
          </span>
          <button className="primary" onClick={newQuestion}>Next</button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ practice */

export function PracticeGuide() {
  const [steps, setSteps] = useState([]);
  useEffect(() => {
    api.practice().then((d) => setSteps(d.steps)).catch(() => {});
  }, []);

  return (
    <div className="card learn-card">
      <h2>How to practise</h2>
      <p className="footnote">
        The habits that decide whether an hour at the piano is worth an hour.
      </p>
      <ol className="practice-list">
        {steps.map((s) => (
          <li key={s.title}>
            <strong>{s.title}</strong>
            <p>{s.text}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
