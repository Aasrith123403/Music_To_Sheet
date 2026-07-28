"""Guard against music symbols that most fonts can't render.

The Unicode "Musical Symbols" block (U+1D100–U+1D1FF) has patchy font coverage.
Clefs happen to be widely supported, but the note-value symbols are not, and
using them produced empty tofu boxes in the Learn page. Those are drawn as SVG
now (``MusicIcon.jsx``); this test stops them creeping back in as characters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"

pytestmark = pytest.mark.skipif(not SRC.is_dir(), reason="frontend not present")

# Codepoints that rendered as boxes and must stay out of the source.
UNRENDERABLE = {
    "\U0001D15D": "whole note",
    "\U0001D15E": "half note",
    "\U0001D15F": "quarter note",
    "\U0001D160": "eighth note",
    "\U0001D161": "sixteenth note",
    "\U0001D165": "combining stem",
    "\U0001D16E": "combining flag",
}


def test_no_unrenderable_note_glyphs():
    offenders = []
    for path in [*SRC.rglob("*.jsx"), *SRC.rglob("*.js")]:
        text = path.read_text()
        for char, name in UNRENDERABLE.items():
            if char in text:
                offenders.append(f"{path.name}: {name} (U+{ord(char):04X})")
    assert not offenders, (
        "these musical-symbol characters render as empty boxes in most fonts — "
        f"use the SVG icons in MusicIcon.jsx instead: {offenders}"
    )


def test_note_value_icons_exist():
    """The SVG replacements are actually present and used."""
    icons = (SRC / "MusicIcon.jsx").read_text()
    for name in ("QuarterNote", "HalfNote", "EighthNote", "BeamedNotes"):
        assert f"export function {name}" in icons

    learn = (SRC / "Learn.jsx").read_text()
    assert "MusicIcon.jsx" in learn
    assert "<HalfNote />" in learn and "<BeamedNotes />" in learn
