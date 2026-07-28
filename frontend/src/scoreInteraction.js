/**
 * Makes a rendered OSMD score interactive: clickable noteheads and a
 * follow-along cursor synced to audio playback.
 *
 * Both features rely on two facts about OSMD's object model, confirmed against
 * the running library rather than assumed:
 *
 *  - every `GraphicalNote` exposes `getSVGGElement()`, the `<g>` actually drawn
 *    on the page, so a click can be tied to a specific note;
 *  - `sourceNote.halfTone` is a semitone index where middle C is 48, i.e.
 *    **MIDI = halfTone + 12**;
 *  - cursor timestamps (`iterator.currentTimeStamp.RealValue`) are measured in
 *    *whole notes*, so seconds = value × 4 × 60 / BPM.
 */

export const HALFTONE_TO_MIDI = 12;

/** Every drawn note, with its SVG element and MIDI pitch. */
export function collectNotes(osmd) {
  const out = [];
  const measures = osmd?.graphic?.measureList || [];
  for (const staves of measures) {
    for (const measure of staves || []) {
      for (const entry of measure?.staffEntries || []) {
        for (const voiceEntry of entry?.graphicalVoiceEntries || []) {
          for (const note of voiceEntry?.notes || []) {
            const source = note.sourceNote;
            if (!source || source.isRestFlag) continue;
            let el = null;
            try {
              el = note.getSVGGElement();
            } catch {
              el = null;
            }
            if (!el) continue;
            out.push({ el, midi: source.halfTone + HALFTONE_TO_MIDI });
          }
        }
      }
    }
  }
  return out;
}

/**
 * Make each notehead clickable. `onNote(midi)` fires on click.
 * Returns a cleanup function.
 *
 * OSMD replaces its whole SVG whenever it re-renders (it does so on resize, and
 * React StrictMode remounts in development), which silently throws away any
 * listeners bound to the old elements. So the bindings are re-applied whenever
 * the container's contents change, and a `WeakSet` keeps that idempotent.
 */
/** The `<g>` VexFlow draws for each notehead group (a chord shares one). */
const NOTE_GROUP_SELECTOR = "g.vf-stavenote";

/**
 * Make noteheads clickable. `onNote(midi, element)` fires on click.
 * Returns a cleanup function.
 *
 * Uses a single delegated listener on the container rather than one per note.
 * That matters here: OSMD swaps its entire SVG on every re-render (resize,
 * remount, reload), and per-element listeners silently died with the old nodes
 * — the notes stayed visible but stopped responding. A delegated listener
 * survives any number of re-renders, and the pitch lookup is resolved at click
 * time against whatever OSMD currently has drawn, so it can never go stale.
 */
export function attachNoteClicks(getOsmd, onNote, container) {
  const host = container || (typeof getOsmd === "function" ? getOsmd()?.container : null);
  if (!host) return () => {};

  const onClick = (event) => {
    const group = event.target?.closest?.(NOTE_GROUP_SELECTOR);
    if (!group || !host.contains(group)) return;

    const osmd = typeof getOsmd === "function" ? getOsmd() : getOsmd;
    if (!osmd) return;

    // Chord members share a group, so collect every pitch drawn in it.
    const midis = collectNotes(osmd)
      .filter((n) => n.el === group || group.contains(n.el))
      .map((n) => n.midi);

    // Fall back to DOM position if OSMD's references don't line up with the
    // drawn SVG (it rebuilds them on re-render).
    let pitches = midis;
    if (!pitches.length) {
      const groups = [...host.querySelectorAll(NOTE_GROUP_SELECTOR)];
      const index = groups.indexOf(group);
      const byGroup = groupNotes(collectNotes(osmd));
      pitches = index >= 0 && byGroup[index] ? byGroup[index] : [];
    }
    if (!pitches.length) return;

    onNote(pitches, group);
    group.classList.add("note-lit");
    setTimeout(() => group.classList.remove("note-lit"), 320);
  };

  host.addEventListener("click", onClick);
  return () => host.removeEventListener("click", onClick);
}

/** Collapse a flat note list into per-notehead-group pitch arrays, in order. */
export function groupNotes(notes) {
  const groups = [];
  let currentEl = null;
  for (const { el, midi } of notes) {
    if (el !== currentEl) {
      groups.push([]);
      currentEl = el;
    }
    groups[groups.length - 1].push(midi);
  }
  return groups;
}

/**
 * Timestamps (seconds) of every cursor stop, plus the notes sounding there.
 * Walking the iterator once up front keeps playback itself cheap.
 */
export function buildSchedule(osmd, bpm) {
  const cursor = osmd?.cursor;
  if (!cursor) return [];
  const secondsPerWhole = (4 * 60) / (bpm || 120);
  const steps = [];

  cursor.reset();
  let guard = 0;
  while (!cursor.iterator.EndReached && guard++ < 20000) {
    const ts = cursor.iterator.currentTimeStamp;
    const midis = (cursor.NotesUnderCursor() || [])
      .filter((n) => !n.isRestFlag)
      .map((n) => n.halfTone + HALFTONE_TO_MIDI);
    steps.push({ seconds: (ts?.RealValue || 0) * secondsPerWhole, midis });
    cursor.next();
  }
  cursor.reset();
  return steps;
}

/**
 * Drive the cursor from an <audio> element.
 *
 * OSMD's cursor only steps forward, so seeking backwards means resetting and
 * replaying the steps — cheap, and it keeps scrubbing accurate.
 * Returns a stop function.
 */
export function followAlong(osmd, audio, schedule, { container, onStep } = {}) {
  const cursor = osmd?.cursor;
  if (!cursor || !audio || !schedule.length) return () => {};

  let index = -1;
  let raf = 0;
  let stopped = false;

  cursor.reset();
  cursor.show();

  const moveTo = (target) => {
    if (target === index) return;
    if (target < index) {
      cursor.reset();
      index = 0;
      for (let i = 0; i < target; i++) cursor.next();
    } else {
      for (let i = index < 0 ? 0 : index; i < target; i++) cursor.next();
    }
    index = target;
    scrollCursorIntoView(cursor, container);
    onStep?.(target, schedule[target]);
  };

  const update = () => {
    if (stopped) return;
    const t = audio.currentTime;
    let target = 0;
    while (target + 1 < schedule.length && schedule[target + 1].seconds <= t) target += 1;
    moveTo(target);
  };

  const tick = () => {
    if (stopped) return;
    update();
    raf = requestAnimationFrame(tick);
  };

  // rAF keeps the cursor smooth, but browsers freeze it in background tabs —
  // `timeupdate` (and `seeked`) keep the score in step when the listener has
  // switched away and comes back, or scrubs the audio.
  audio.addEventListener("timeupdate", update);
  audio.addEventListener("seeked", update);
  raf = requestAnimationFrame(tick);
  update();

  return () => {
    stopped = true;
    cancelAnimationFrame(raf);
    audio.removeEventListener("timeupdate", update);
    audio.removeEventListener("seeked", update);
    try {
      cursor.hide();
    } catch {
      /* already gone */
    }
  };
}

/** Keep the cursor visible without yanking the whole page around. */
export function scrollCursorIntoView(cursor, container) {
  const el = cursor?.cursorElement;
  if (!el || !container) return;
  const c = container.getBoundingClientRect();
  const e = el.getBoundingClientRect();
  // Horizontal: the score scrolls sideways inside its own box.
  if (e.left < c.left + 40 || e.right > c.right - 40) {
    container.scrollLeft += e.left - c.left - c.width / 3;
  }
  // Vertical: only scroll the page when the cursor has left the viewport.
  if (e.top < 0 || e.bottom > window.innerHeight) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}
