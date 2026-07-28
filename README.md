# Audio → Sheet Music

Upload a single-instrument recording, get back readable sheet music — with a measurable claim about *how* readable it is, plus
an analysis of what was played.

**Scope constraint (the thing that makes it finishable):** one instrument per
recording. No source separation, no multi-instrument mixes, no vocals-over-band.
Pick the instrument up front; the pipeline notates it with the correct clef,
range, and transposition.

## Features

- **Instruments** — piano (grand staff) plus guitar, bass, violin, viola,
  cello, flute, clarinet, alto sax, trumpet, voice. Transposing instruments
  (B♭/E♭) are written at concert-correct pitch. Chosen from a dropdown.
- **Chords** — simultaneous notes are grouped into chords (left-hand block
  chords read as chords, not a pile of overlapping noteheads), and a cost-based
  Viterbi assigns each note to a hand instead of a hard middle-C split.
- **Sheet → Audio (reverse)** — upload notation and hear it played in a chosen
  instrument. MusicXML/MIDI play back exactly; PDF/image go through optical
  music recognition (OMR, `oemer`) — best-effort, accuracy depends on the scan.
  Playback is rendered offline with fluidsynth + a bundled GM soundfont (falls
  back to a browser MIDI player, which needs network, if fluidsynth is absent).
- **Analysis** — key/scale, tempo, time signature, duration, note count, pitch
  range, texture (mono/poly), dynamics, and most-used notes.
- **Exports** — download any score as PDF, MusicXML, or (for synthesized
  pieces) MIDI.
- **Accounts & library** — register with email/password or Google, and every
  transcription you make while signed in is saved with its key, tempo,
  difficulty and files. Rename, reopen, delete. Signing in is optional: the
  studio works signed out, the work just isn't kept.
- **Interactive score** — click any notehead to hear it, step through with
  Prev/Next, and switch on *Follow the score* so a cursor tracks the audio and
  scrolls the page as it plays.
- **Learn** — nine sections for actually learning the piano: a note-reading
  trainer on real engraved staves (answer with the letter keys), **scales with
  standard piano fingering** for every key, a **metronome** with accented
  downbeats, **chord** and **interval** ear-training, a playable keyboard, a
  symbol reference, a clickable circle-of-fifths that plays each scale, and a
  practice guide. Every piece also gets a 1–5 reading-difficulty rating.
- **Chords** — build any chord from a root/quality/inversion (engraved, spelled
  and played), stack notes on a keyboard to find out what you've invented, and
  browse the chords and stock progressions of any key.
- **Readability metrics** — three tiers (below), the point of the project.

## Transcription models

| instrument | model | measured onset F1 |
|---|---|---|
| piano | `piano_transcription_inference` (ByteDance) | **0.976** |
| piano | basic-pitch (fallback) | 0.712 |
| everything else | basic-pitch, band-limited to the instrument's range | — |

Measured against ground truth on sampled-piano audio. The piano model is used
automatically when installed (`pip install -e ".[piano]"`); without it
everything still works through basic-pitch. Note the earlier figures in this
README were measured on *synthetic* tones, where the ranking reverses — the
piano model expects real piano timbre, so benchmark it on realistic audio.

## Accounts and Google sign-in

Email/password accounts work out of the box (bcrypt hashes, HttpOnly session
cookies, server-side revocation on logout). **Google sign-in is optional and
off until you supply credentials** — the API reports it as unavailable and the
UI hides the button.

To enable it, create an OAuth client at
<https://console.cloud.google.com/apis/credentials> (type: *Web application*),
add `http://localhost:8000/auth/google/callback` as an authorised redirect URI,
then export:

```bash
export GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="..."
export GOOGLE_REDIRECT_URI="http://localhost:8000/auth/google/callback"
export PIANO_APP_URL="http://localhost:5173/"   # where to land after sign-in
```

**Before putting this on the public internet**, note what the auth layer
deliberately does *not* include: email verification, password reset, rate
limiting on login, or CSRF tokens on state-changing calls (session cookies are
`SameSite=Lax`, which covers the common cases but is not a substitute). Also set
`PIANO_COOKIE_SECURE=1` so cookies are HTTPS-only, and move off SQLite if you
expect real concurrency.

## Pipeline

```
audio → transcribe → [NoteEvent(pitch, onset_s, offset_s, velocity)]
      → gate        → decline un-notatable audio (speech, dense mix, too long)
      → beats       → BeatGrid (time-varying beat sequence + time signature)
      → quantize    → notated durations on a metrical grid
      → voices      → staff/voice assignment (grand staff for piano)
      → spelling    → key estimate + enharmonic accidentals (+ transposition)
      → notate      → music21 Score → MusicXML
      → analyze     → summary stats for the analysis panel
      → (frontend)  → OpenSheetMusicDisplay renders the score
```

`NoteEvent` is the stable interface between transcription and everything
downstream — swap the model without touching later stages.

## Layout

```
piano_transcribe/     the pipeline library
  types.py            NoteEvent, QuantizedNote, BeatGrid  (the interfaces)
  instruments.py      instrument registry (range, clef, transposition)
  transcribe.py       audio → note events   (basic-pitch)
  beats.py            beat tracking          (librosa)
  quantize.py         metrical quantization  (baseline + cost-based)
  voices.py           staff/voice assignment (split + cost-based Viterbi)
  spelling.py         key + enharmonics      (Krumhansl-Schmuckler)
  notate.py           music21 → MusicXML     (grand/single staff, chord grouping)
  cleanup.py          strip transcription artifacts (ghosts, specks, fragments)
  analyze.py          analysis summary
  quality.py          transcribability gate
  importscore.py      sheet music → music21 Score (MusicXML/MIDI; PDF/image OMR)
  synthesize.py       Score → MIDI (instrument) + analysis   (reverse direction)
  learn.py            note quiz, scales + fingering, difficulty, key reference
  chords.py           chord building, identification, keys and progressions
  evaluate.py         mir_eval metrics (three tiers) + notation fidelity
  pipeline.py         end-to-end orchestration
api/                  FastAPI: accounts, jobs, library, learning
  main.py db.py jobs.py auth.py google_oauth.py config.py
cli/run_eval.py       score a MAESTRO subset, print/write a metrics table
cli/bench_quantize.py rhythm benchmark for the notation layer (no dataset)
frontend/             React + Vite + OSMD
  App.jsx api.js AuthPanel.jsx Library.jsx Learn.jsx ScoreResult.jsx
tests/                pytest — incl. the self-scoring F1 == 1.0 check
```

## Metrics (three tiers)

1. **Note accuracy** — onset F1 / onset+offset F1 (`mir_eval`). Measures the
   *model*, not your notation work.
2. **Rhythmic accuracy** — fraction of notes given the correct notated
   duration vs. ground truth on the same grid. What the quantizer moves.
3. **Notation complexity** — tuplets, cross-barline ties, accidentals per
   measure. Lower is better at equal rhythmic accuracy — the readability proxy.

All three are implemented; `python -m cli.run_eval --full` reports them together.

### Rhythm benchmark (no dataset needed)

`cli/bench_quantize.py` scores the notation layer against synthetic pieces whose
rhythm is known exactly, so quantizer/beat-tracking changes have a number to
move without downloading MAESTRO:

```bash
python -m cli.bench_quantize --grid perfect    # isolates the quantizer
python -m cli.bench_quantize --grid tracked    # adds beat-tracking error
```

Both currently score 100% onset/duration at human-level timing jitter (≈10–20 ms),
degrading gracefully as jitter grows relative to the beat (≈75–85% at 50 ms).
This harness is what caught the accuracy bugs listed below — run it before and
after any change to `quantize.py` or `beats.py`.

Plus one human check no metric replaces: transcribe a piece you can play, then
sight-read the output.

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # library + pytest
pip install -e ".[transcribe]"   # add basic-pitch (pulls in TensorFlow)
pip install -e ".[api]"          # FastAPI + uvicorn + pymupdf
pip install -e ".[omr]"          # optional: oemer, for PDF/image sheet input
# fluidsynth  — for offline Sheet→Audio playback    (brew install fluid-synth)
```

**OMR engines** (for PDF/image sheet input) — the app prefers **Audiveris** (a
Java OMR app; far more robust) and falls back to **oemer** (pip). Detection
order: `$AUDIVERIS_CMD` / `$AUDIVERIS_JAR`, then `audiveris` on PATH, then
`~/audiveris/bin/Audiveris`; force an engine with
`$PIANO_OMR_ENGINE=audiveris|oemer` (default `auto`). Audiveris needs Java 25+
and Tesseract (`brew install tesseract`; the app points `TESSDATA_PREFIX` at the
brew location automatically). Build it from source once
(`git clone …/Audiveris && ./gradlew :app:installDist`) and the app finds the
result under `~/audiveris`.

**Important — OMR wants real scans.** Both engines work on genuine
scanned/photographed pages (~300 dpi) but fail on clean, computer-generated
renders: Audiveris aborts with "no regularly spaced lines found" and oemer
crashes in dewarping. Any OMR failure is caught and returned to the UI as a
"couldn't process this" rejection, so the app never breaks — but for image
input, feed it an actual scan, not a screenshot of digital notation.

`oemer` (if used) downloads ~230 MB of models on first run; the app sets
`SSL_CERT_FILE` from certifi so that works on python.org builds. A GM soundfont
ships with pretty_midi for offline playback, or point `$PIANO_SOUNDFONT` at your
own `.sf2`.

## Run

```bash
pytest                                   # 143 tests, incl. self-scoring F1 == 1.0
uvicorn api.main:app --reload            # API at http://127.0.0.1:8000/docs

# frontend (needs the API running; proxies /jobs + /instruments -> :8000)
cd frontend && npm install && npm run dev   # http://127.0.0.1:5173

# eval over MAESTRO (needs the [transcribe] + [eval] extras):
python -m cli.run_eval --maestro /path/to/maestro-v3.0.0 --limit 10 --out data/eval.csv
python -m cli.run_eval --maestro /path/to/maestro-v3.0.0 --limit 10 --full   # + tiers 2/3
```

`frontend/render-test.html` renders a bundled sample score with OSMD (no
backend needed) — handy for iterating on notation. Serve `frontend/` statically
(`python -m http.server`) and open it.

## Build order

- **Week 1 — eval first, then baseline.** `evaluate.py` scores ground truth
  against itself and returns 1.0 (see `tests/test_evaluate.py`). Then
  basic-pitch → naive quantization → music21 → MusicXML: ugly, end to end,
  with a number attached.
- **Week 2 — API + UI.** Upload, background job, polling, render. Now it's a
  thing you can show someone.
- **Weeks 3+ — pick one sub-problem and go deep.** Quantization is highest
  value; voice separation is the most tractable early win. Do one well —
  four half-solutions is a worse project than one solved problem.

Feed the eval numbers back into each quantizer change — that loop is what makes
this a project with a result rather than a demo.

## On sharing output

Transcribing recordings for your own study is fine, but the underlying
compositions are usually still under copyright — don't publish generated
scores. For any public demo use your own playing or public-domain recordings
(pre-1930 piano repertoire; MAESTRO is convenient for screenshots).

## Status

All stages are implemented end to end — `run_pipeline` takes an audio file to a
`.musicxml`, and the React/OSMD frontend renders it as a grand staff.

| Stage | Baseline | Deep-dive |
|-------|----------|-----------|
| transcribe | basic-pitch behind a swappable `Transcriber` | — |
| beats | `librosa.beat.beat_track` (a sequence, not a BPM) | meter inference (TODO) |
| quantize | `quantize_nearest` (1/4-beat grid) | `quantize_cost` (α·displacement + β·complexity, per-beat subdivision search, tuplet-aware) |
| voices | `assign_middle_c_split` | `assign_cost` (two-state Viterbi: switch/span/crossing penalties) |
| spelling | Krumhansl-Schmuckler key + global sharp/flat | per-measure enharmonic consistency (TODO) |
| notate | two-staff music21 → MusicXML, balanced grand staff | multi-voice / chord splitting (TODO) |
| evaluate | tier-1 onset/offset F1 | tier-2 rhythmic accuracy, tier-3 complexity |
| eval CLI | MAESTRO index + MIDI loading | `--full` scores all three tiers per piece |

Remaining depth to add (all have honest TODOs where they'd slot in): meter
inference beyond 4/4, per-measure enharmonic consistency, and multi-voice /
chord splitting within a staff. Feed the eval numbers back into each quantizer
change — that loop is what makes this a project with a result, not a demo.
