import { forwardRef, useEffect, useRef } from "react";
import "html-midi-player";

// Thin wrapper around the <midi-player> web component. The empty `sound-font`
// attribute makes it use the default General MIDI soundfont (fetched at play
// time, so playback needs a network connection); the instrument timbre comes
// from the MIDI program the backend stamped in.
//
// The element is forwarded so the score can follow along with it: like <audio>
// it exposes `currentTime` in seconds, which is all the cursor needs.
const MidiPlayer = forwardRef(function MidiPlayer({ src }, ref) {
  const localRef = useRef(null);

  useEffect(() => {
    const el = localRef.current;
    if (!el) return;
    el.setAttribute("sound-font", "");
    if (src) el.src = src;
  }, [src]);

  return (
    <div className="player">
      <midi-player
        ref={(el) => {
          localRef.current = el;
          if (typeof ref === "function") ref(el);
          else if (ref) ref.current = el;
        }}
        sound-font=""
      />
    </div>
  );
});

export default MidiPlayer;
