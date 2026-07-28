import { useCallback, useEffect, useRef, useState } from "react";
import { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import { api } from "./api.js";
import { BeamedNotes, EighthNote, HalfNote, QuarterNote } from "./MusicIcon.jsx";
import Keyboard from "./Keyboard.jsx";
import { midiToName, playNote, playSequence, primeAudio } from "./audio.js";

/** Renders one engraved flashcard note. */
function Flashcard({ musicxml }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!musicxml || !ref.current) return;
    const host = ref.current;
    let cancelled = false;
    (async () => {
      // Clear first: OSMD *appends* its SVG, so re-running this effect (React
      // StrictMode does in dev) would stack a second staff on top of the first.
      host.innerHTML = "";
      const osmd = new OpenSheetMusicDisplay(host, {
        autoResize: false,
        drawTitle: false,
        drawSubtitle: false,
        drawComposer: false,
        drawCredits: false,
        drawPartNames: false,
        drawMeasureNumbers: false,
        backend: "svg",
      });
      await osmd.load(musicxml);
      if (cancelled) return;
      osmd.zoom = 1.4;
      osmd.render();
    })();
    return () => {
      cancelled = true;
      host.innerHTML = "";
    };
  }, [musicxml]);

  return <div className="flashcard" ref={ref} />;
}

const LETTERS = ["C", "D", "E", "F", "G", "A", "B"];

function NoteTrainer() {
  const [clef, setClef] = useState("treble");
  const [cards, setCards] = useState([]);
  const [idx, setIdx] = useState(0);
  const [picked, setPicked] = useState(null);
  const [score, setScore] = useState({ right: 0, total: 0 });
  const [loading, setLoading] = useState(false);
  const [streak, setStreak] = useState(0);
  const [best, setBest] = useState(0);

  const card = cards[idx];
  const done = cards.length > 0 && idx >= cards.length;

  const start = useCallback(async (nextClef) => {
    setLoading(true);
    try {
      const res = await api.quiz(nextClef, 10);
      setCards(res.cards);
      setIdx(0);
      setPicked(null);
      setScore({ right: 0, total: 0 });
      setStreak(0);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    start(clef);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const midi = card ? (LETTERS.indexOf(card.answer) >= 0
    ? [0, 2, 4, 5, 7, 9, 11][LETTERS.indexOf(card.answer)] + (card.octave + 1) * 12
    : null) : null;

  const choose = useCallback(
    (option) => {
      if (picked || !card) return;
      const correct = option === card.answer;
      setPicked(option);
      setScore((s) => ({ right: s.right + (correct ? 1 : 0), total: s.total + 1 }));
      setStreak((s) => {
        const next = correct ? s + 1 : 0;
        setBest((b) => Math.max(b, next));
        return next;
      });
      // Hearing the note right after answering is what ties the symbol to a sound.
      if (midi != null) {
        primeAudio();
        playNote(midi);
      }
    },
    [picked, card, midi]
  );

  const next = useCallback(() => {
    setPicked(null);
    setIdx((i) => i + 1);
  }, []);

  // Answer from the keyboard: letter keys pick, Enter/Space advances.
  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.target.tagName === "INPUT") return;
      const letter = e.key.toUpperCase();
      if (!picked && card && LETTERS.includes(letter)) {
        if (card.options.includes(letter)) choose(letter);
      } else if (picked && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        next();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [picked, card, choose, next]);

  return (
    <div className="card learn-card">
      <div className="learn-head">
        <h2>Note reading</h2>
        <div className="clef-picker">
          {["treble", "bass", "grand"].map((c) => (
            <button
              key={c}
              className={`tab ${clef === c ? "active" : ""}`}
              onClick={() => {
                setClef(c);
                start(c);
              }}
            >
              {c === "grand" ? "Both" : c}
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="footnote">Preparing staves…</p>}

      {!loading && done && (
        <div className="quiz-done">
          <p className="quiz-score">
            {score.right} / {score.total} correct
          </p>
          <p className="footnote">
            Best streak this round: {best}.{" "}
            {score.right === score.total
              ? "Perfect — try the other clef next."
              : "The notes you miss are the ones worth repeating."}
          </p>
          <button className="primary" onClick={() => start(clef)}>
            New round
          </button>
        </div>
      )}

      {!loading && card && !done && (
        <>
          <div className="quiz-status">
            <span className="quiz-progress">
              Note {idx + 1} of {cards.length} · {score.right}/{score.total} correct
            </span>
            {streak >= 2 && <span className="streak">🔥 {streak} in a row</span>}
          </div>

          <Flashcard musicxml={card.musicxml} />

          <div className="quiz-prompt-row">
            <p className="quiz-prompt">Which note is this?</p>
            {midi != null && (
              <button
                className="link-btn"
                onClick={() => {
                  primeAudio();
                  playNote(midi);
                }}
              >
                ♪ Hear it
              </button>
            )}
          </div>

          <div className="options">
            {card.options.map((opt) => {
              const isAnswer = opt === card.answer;
              const cls = picked
                ? isAnswer
                  ? "option correct"
                  : opt === picked
                  ? "option wrong"
                  : "option"
                : "option";
              return (
                <button key={opt} className={cls} onClick={() => choose(opt)}>
                  {opt}
                </button>
              );
            })}
          </div>
          <p className="footnote kbd-hint">
            Tip: press the letter keys to answer, then Enter for the next note.
          </p>

          {picked && (
            <div className="quiz-feedback">
              <span>
                {picked === card.answer
                  ? "Correct."
                  : `That was ${card.answer}${card.octave}.`}
              </span>
              <button className="primary" onClick={next}>
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

const INTERVALS = [
  [0, "Unison"], [1, "Minor 2nd"], [2, "Major 2nd"], [3, "Minor 3rd"],
  [4, "Major 3rd"], [5, "Perfect 4th"], [7, "Perfect 5th"], [8, "Minor 6th"],
  [9, "Major 6th"], [10, "Minor 7th"], [11, "Major 7th"], [12, "Octave"],
];

function EarTrainer() {
  const [current, setCurrent] = useState(null);
  const [picked, setPicked] = useState(null);
  const [score, setScore] = useState({ right: 0, total: 0 });
  const [pool, setPool] = useState(4); // how many intervals are in play

  const choices = INTERVALS.slice(0, pool);

  const newQuestion = useCallback(() => {
    const [semitones, name] = choices[Math.floor(Math.random() * choices.length)];
    const root = 57 + Math.floor(Math.random() * 8); // around A3-F4
    const q = { semitones, name, root };
    setCurrent(q);
    setPicked(null);
    primeAudio();
    playSequence([root, root + semitones]);
    return q;
  }, [choices]);

  useEffect(() => {
    newQuestion();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pool]);

  function answer(name) {
    if (picked || !current) return;
    setPicked(name);
    setScore((s) => ({
      right: s.right + (name === current.name ? 1 : 0),
      total: s.total + 1,
    }));
  }

  return (
    <div className="card learn-card">
      <div className="learn-head">
        <h2>Hearing intervals</h2>
        <div className="clef-picker">
          {[4, 8, 12].map((n) => (
            <button
              key={n}
              className={`tab ${pool === n ? "active" : ""}`}
              onClick={() => setPool(n)}
            >
              {n === 4 ? "Easy" : n === 8 ? "Medium" : "All"}
            </button>
          ))}
        </div>
      </div>
      <p className="footnote">
        Two notes play in turn. Name the distance between them — the skill behind
        reading a leap on the page and knowing how it should sound.
      </p>

      <div className="ear-controls">
        <button
          className="primary"
          onClick={() => {
            if (!current) return;
            primeAudio();
            playSequence([current.root, current.root + current.semitones]);
          }}
        >
          ♪ Play again
        </button>
        <span className="quiz-progress">
          {score.right}/{score.total} correct
        </span>
      </div>

      <div className="options interval-options">
        {choices.map(([, name]) => {
          const cls = picked
            ? name === current?.name
              ? "option correct"
              : name === picked
              ? "option wrong"
              : "option"
            : "option";
          return (
            <button key={name} className={cls} onClick={() => answer(name)}>
              {name}
            </button>
          );
        })}
      </div>

      {picked && (
        <div className="quiz-feedback">
          <span>
            {picked === current.name
              ? "Correct."
              : `That was a ${current.name}.`}
          </span>
          <button className="primary" onClick={newQuestion}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function KeyboardExplorer() {
  const [last, setLast] = useState(null);
  return (
    <div className="card learn-card">
      <h2>The keyboard</h2>
      <p className="footnote">
        Play a key to hear it and see its name. The white keys are the seven
        letters A–G repeating; each black key is the sharp of the white below it
        (and the flat of the white above).
      </p>
      <Keyboard startOctave={4} octaves={2} onKey={setLast} />
      <p className="keyboard-readout">
        {last != null ? midiToName(last) : "—"}
      </p>
    </div>
  );
}

// Clefs and accidentals are drawn from Unicode (those glyphs have broad font
// coverage); note values are SVG, because the Musical Symbols block ones don't.
const BASICS = [
  ["𝄞", "Treble clef", "The G line curls around the second line up — right hand, higher notes."],
  ["𝄢", "Bass clef", "The two dots hug the F line — left hand, lower notes."],
  [<QuarterNote />, "Quarter note", "One beat in common time. A filled head with a stem."],
  [<HalfNote />, "Half note", "Two beats — a hollow head with a stem."],
  [<EighthNote />, "Eighth note", "Half a beat — a flag (or a beam joining its neighbours)."],
  [<BeamedNotes />, "Beamed notes", "Flags joined into beams so beats stay easy to see."],
  ["♯", "Sharp", "Raises the note a semitone until the end of the bar."],
  ["♭", "Flat", "Lowers the note a semitone until the end of the bar."],
  ["♮", "Natural", "Cancels a sharp or flat for the rest of the bar."],
];

function Basics() {
  return (
    <div className="card learn-card">
      <h2>Reading the page</h2>
      <div className="basics-grid">
        {BASICS.map(([glyph, name, text]) => (
          <div className="basic" key={name}>
            <span className="glyph">{glyph}</span>
            <div>
              <strong>{name}</strong>
              <p>{text}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const SCALE_STEPS = [0, 2, 4, 5, 7, 9, 11, 12];

function KeyReference() {
  const [keys, setKeys] = useState([]);
  const [playing, setPlaying] = useState(null);

  useEffect(() => {
    api.keys().then((r) => setKeys(r.keys)).catch(() => {});
  }, []);

  // Tonic pitch classes in circle-of-fifths order, matching the API's ordering.
  const tonicPc = (major) => {
    const base = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[major[0]] ?? 0;
    if (major.includes("♭")) return (base + 11) % 12;
    if (major.includes("#")) return (base + 1) % 12;
    return base;
  };

  return (
    <div className="card learn-card">
      <h2>Key signatures</h2>
      <p className="footnote">
        Each key signature is shared by one major and one minor key — the
        “relative” pair. Sharps are added in the order F C G D A E B; flats in
        the reverse. Click a key to hear its scale.
      </p>
      <div className="key-grid">
        {keys.map((k) => (
          <button
            className={`key-cell ${playing === k.major ? "playing" : ""}`}
            key={k.major}
            onClick={() => {
              primeAudio();
              const root = 60 + tonicPc(k.major);
              setPlaying(k.major);
              const ms = playSequence(SCALE_STEPS.map((s) => root + s), { gap: 0.28, duration: 0.4 });
              setTimeout(() => setPlaying((p) => (p === k.major ? null : p)), ms);
            }}
          >
            <div className="key-major">{k.major}</div>
            <div className="key-minor">{k.minor}</div>
            <div className="key-acc">{k.accidentals}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Learn() {
  return (
    <div className="learn">
      <NoteTrainer />
      <EarTrainer />
      <KeyboardExplorer />
      <Basics />
      <KeyReference />
    </div>
  );
}
