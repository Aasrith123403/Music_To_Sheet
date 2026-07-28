function Stat({ label, value, sub }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value ?? "—"}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  );
}

export default function AnalysisPanel({ analysis: a }) {
  if (!a) return null;
  const range = a.pitch_range || {};
  const dyn = a.dynamics || {};

  return (
    <div className="card analysis">
      <div className="analysis-head">
        <h2>Analysis</h2>
        {a.instrument && <span className="pill">{a.instrument}</span>}
        {a.difficulty && (
          <span className={`pill diff-pill diff-${a.difficulty.level}`}>
            {a.difficulty.label}
          </span>
        )}
      </div>

      {a.difficulty?.reasons?.length > 0 && (
        <p className="footnote difficulty-note">
          Reading difficulty {a.difficulty.level}/5 — {a.difficulty.reasons.join(", ")}.
        </p>
      )}

      <div className="stat-grid">
        <Stat
          label="Key"
          value={a.key}
          sub={a.key_confidence != null ? `confidence ${a.key_confidence}` : null}
        />
        <Stat label="Tempo" value={a.tempo_bpm ? `${a.tempo_bpm} BPM` : null} />
        <Stat label="Time signature" value={a.time_signature} />
        <Stat label="Duration" value={a.duration_hms} />
        <Stat label="Notes" value={a.num_notes} sub={`${a.notes_per_second}/sec`} />
        <Stat
          label="Range"
          value={range.low && range.high ? `${range.low}–${range.high}` : null}
          sub={range.span_semitones ? `${range.span_semitones} semitones` : null}
        />
        <Stat label="Texture" value={a.texture} sub={`max ${a.max_polyphony} at once`} />
        <Stat
          label="Dynamics"
          value={dyn.mean_velocity != null ? `avg ${dyn.mean_velocity}` : null}
          sub={dyn.min_velocity != null ? `${dyn.min_velocity}–${dyn.max_velocity}` : null}
        />
        {a.fidelity?.onset != null && (
          <Stat
            label="Notation fidelity"
            value={`${Math.round(a.fidelity.onset * 100)}%`}
            sub={`durations ${Math.round(a.fidelity.duration * 100)}%`}
          />
        )}
      </div>

      {a.fidelity?.onset != null && (
        <p className="footnote">
          Notation fidelity = share of notes written within a 32nd note of where
          they were played. It checks the notation, not whether the notes
          themselves were heard correctly — for that, play the score back and
          compare it with your recording.
        </p>
      )}

      {a.scale && a.scale.length > 0 && (
        <div className="chips-row">
          <span className="chips-label">Scale</span>
          <div className="chips">
            {a.scale.map((n, i) => (
              <span className="chip" key={`${n}-${i}`}>
                {n}
              </span>
            ))}
          </div>
        </div>
      )}

      {a.top_pitch_classes && a.top_pitch_classes.length > 0 && (
        <div className="chips-row">
          <span className="chips-label">Most used</span>
          <div className="chips">
            {a.top_pitch_classes.map((p) => (
              <span className="chip chip-count" key={p.name}>
                {p.name} <em>{p.count}</em>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
