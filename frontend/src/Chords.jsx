import { useCallback, useEffect, useRef, useState } from "react";
import { OpenSheetMusicDisplay } from "opensheetmusicdisplay";
import { api } from "./api.js";
import Keyboard from "./Keyboard.jsx";
import { midiToName, playChord, playSequence, primeAudio } from "./audio.js";

/** Small engraved staff for a single chord. */
function ChordStaff({ musicxml }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!musicxml || !ref.current) return;
    const host = ref.current;
    let cancelled = false;
    (async () => {
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
      osmd.zoom = 1.1;
      osmd.render();
    })();
    return () => {
      cancelled = true;
      host.innerHTML = "";
    };
  }, [musicxml]);

  return <div className="chord-staff" ref={ref} />;
}

function Builder() {
  const [notes, setNotes] = useState([]);
  const [qualities, setQualities] = useState([]);
  const [root, setRoot] = useState(0);
  const [quality, setQuality] = useState("maj");
  const [inversion, setInversion] = useState(0);
  const [chord, setChord] = useState(null);

  useEffect(() => {
    api.chordQualities()
      .then((d) => {
        setQualities(d.qualities);
        setNotes(d.notes);
      })
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    try {
      const c = await api.buildChord(root, quality, inversion);
      setChord(c);
    } catch {
      /* ignore */
    }
  }, [root, quality, inversion]);

  useEffect(() => {
    load();
  }, [load]);

  function play() {
    if (!chord) return;
    primeAudio();
    playChord(chord.pitches);
  }

  function arpeggiate() {
    if (!chord) return;
    primeAudio();
    playSequence(chord.pitches, { gap: 0.22, duration: 0.9 });
  }

  const maxInversion = chord ? chord.pitches.length - 1 : 3;

  return (
    <div className="card learn-card">
      <h2>Build a chord</h2>
      <p className="footnote">
        Pick a root and a quality; the chord is engraved, spelled out and played
        back. Inversions move the lowest note up an octave — the same chord, a
        different shape under the hand.
      </p>

      <div className="chord-controls">
        <label className="field">
          <span className="field-label">Root</span>
          <select value={root} onChange={(e) => setRoot(Number(e.target.value))}>
            {notes.map((n, i) => (
              <option key={n} value={i}>{n}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Quality</span>
          <select value={quality} onChange={(e) => setQuality(e.target.value)}>
            {qualities.map((q) => (
              <option key={q.key} value={q.key}>{q.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Inversion</span>
          <select
            value={inversion}
            onChange={(e) => setInversion(Number(e.target.value))}
          >
            {Array.from({ length: maxInversion + 1 }, (_, i) => (
              <option key={i} value={i}>
                {i === 0 ? "root position" : `${i}${i === 1 ? "st" : i === 2 ? "nd" : "rd"}`}
              </option>
            ))}
          </select>
        </label>
      </div>

      {chord && (
        <>
          <div className="chord-headline">
            <span className="chord-name">{chord.name}</span>
            <span className="chord-full">{chord.full_name}</span>
          </div>
          <div className="chord-body">
            <ChordStaff musicxml={chord.musicxml} />
            <div className="chord-side">
              <div className="chord-notes">
                {chord.pitches.map((p) => (
                  <span className="chip" key={p}>{midiToName(p)}</span>
                ))}
              </div>
              <div className="chord-actions">
                <button className="primary" onClick={play}>♪ Play</button>
                <button className="ghost-btn" onClick={arpeggiate}>Arpeggiate</button>
              </div>
            </div>
          </div>
          <Keyboard startOctave={3} octaves={3} highlight={chord.pitches} showLabels={false} />
        </>
      )}
    </div>
  );
}

function Identifier() {
  const [selected, setSelected] = useState([]);
  const [result, setResult] = useState(null);

  const toggle = (midi) => {
    setSelected((prev) =>
      prev.includes(midi) ? prev.filter((p) => p !== midi) : [...prev, midi].sort((a, b) => a - b)
    );
  };

  useEffect(() => {
    if (!selected.length) {
      setResult(null);
      return;
    }
    api.identifyChord(selected).then(setResult).catch(() => {});
  }, [selected]);

  return (
    <div className="card learn-card">
      <h2>Make your own chord</h2>
      <p className="footnote">
        Click keys to stack up any set of notes and see what you've built —
        including inversions and near-misses. This is the quickest way to find
        out that the shape under your fingers already has a name.
      </p>

      <Keyboard
        startOctave={3}
        octaves={3}
        highlight={selected}
        showLabels={false}
        onKey={toggle}
      />

      <div className="identify-row">
        <div className="chord-notes">
          {selected.length ? (
            selected.map((p) => (
              <span className="chip" key={p}>{midiToName(p)}</span>
            ))
          ) : (
            <span className="footnote">No notes selected yet.</span>
          )}
        </div>
        <div className="chord-actions">
          <button
            className="primary"
            disabled={!selected.length}
            onClick={() => {
              primeAudio();
              playChord(selected);
            }}
          >
            ♪ Play
          </button>
          <button className="ghost-btn" onClick={() => setSelected([])}>Clear</button>
        </div>
      </div>

      {result && (
        <div className={`identify-result ${result.exact ? "exact" : "approx"}`}>
          <span className="chord-name">{result.name}</span>
          <span className="chord-full">{result.full_name}</span>
        </div>
      )}
    </div>
  );
}

const MODES = ["major", "minor"];

function KeyChords() {
  const [tonic, setTonic] = useState(0);
  const [mode, setMode] = useState("major");
  const [data, setData] = useState(null);
  const [notes, setNotes] = useState([]);
  const [playing, setPlaying] = useState(null);

  useEffect(() => {
    api.chordQualities().then((d) => setNotes(d.notes)).catch(() => {});
  }, []);

  useEffect(() => {
    api.chordKey(tonic, mode).then(setData).catch(() => {});
  }, [tonic, mode]);

  function playProgression(prog) {
    primeAudio();
    setPlaying(prog.name);
    prog.chords.forEach((c, i) => {
      setTimeout(() => playChord(c.pitches, { duration: 1.1 }), i * 850);
    });
    setTimeout(() => setPlaying((p) => (p === prog.name ? null : p)), prog.chords.length * 850);
  }

  return (
    <div className="card learn-card">
      <div className="learn-head">
        <h2>Chords in a key</h2>
        <div className="chord-controls compact">
          <select value={tonic} onChange={(e) => setTonic(Number(e.target.value))}>
            {notes.map((n, i) => (
              <option key={n} value={i}>{n}</option>
            ))}
          </select>
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            {MODES.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
      </div>

      {data && (
        <>
          <p className="footnote">
            The seven chords built from the notes of the key. Roman numerals are
            how musicians name them independently of key — capitals for major,
            lower case for minor.
          </p>
          <div className="degree-grid">
            {data.diatonic.map((c) => (
              <button
                className="degree"
                key={c.numeral}
                onClick={() => {
                  primeAudio();
                  playChord(c.pitches);
                }}
              >
                <span className="numeral">{c.numeral}</span>
                <span className="degree-name">{c.name}</span>
                <span className="degree-notes">{c.note_names.join(" ")}</span>
              </button>
            ))}
          </div>

          <h3 className="sub-head">Progressions to try</h3>
          <div className="progressions">
            {data.progressions.map((p) => (
              <div className={`progression ${playing === p.name ? "playing" : ""}`} key={p.name}>
                <div className="prog-main">
                  <span className="prog-name">{p.name}</span>
                  <span className="prog-chords">
                    {p.chords.map((c) => c.name).join(" → ")}
                  </span>
                  <span className="footnote">{p.description}</span>
                </div>
                <button className="primary" onClick={() => playProgression(p)}>
                  ♪ Play
                </button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function Chords() {
  return (
    <div className="learn">
      <Builder />
      <Identifier />
      <KeyChords />
    </div>
  );
}
