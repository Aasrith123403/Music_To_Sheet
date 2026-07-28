import { useEffect, useRef } from "react";
import "html-midi-player";

// Thin wrapper around the <midi-player> web component. The empty `sound-font`
// attribute makes it use the default General MIDI soundfont (fetched at play
// time, so playback needs a network connection); the instrument timbre comes
// from the MIDI program the backend stamped in.
export default function MidiPlayer({ src }) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.setAttribute("sound-font", "");
    if (src) el.src = src;
  }, [src]);

  return (
    <div className="player">
      <midi-player ref={ref} sound-font="" />
    </div>
  );
}
