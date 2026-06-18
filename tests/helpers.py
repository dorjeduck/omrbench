"""Small builders for test music21 scores / MusicXML files.

Event specs (used by build_score):
    ("N", "C4", 1.0)            a note (pitch, quarterLength)
    ("R", 1.0)                  a rest (quarterLength)
    ("C", ["C4", "E4"], 1.0)    a chord (pitches, quarterLength)
    ("K", 2)                    a key signature (number of sharps; negative = flats)
"""

from __future__ import annotations

from pathlib import Path

from music21 import chord, key, note, stream


def build_part(events: list) -> stream.Part:
    part = stream.Part()
    for ev in events:
        kind = ev[0]
        if kind == "N":
            part.append(note.Note(ev[1], quarterLength=ev[2]))
        elif kind == "R":
            part.append(note.Rest(quarterLength=ev[1]))
        elif kind == "C":
            part.append(chord.Chord(ev[1], quarterLength=ev[2]))
        elif kind == "K":
            part.append(key.KeySignature(ev[1]))
        else:  # pragma: no cover - guards test typos
            raise ValueError(f"unknown event kind: {kind!r}")
    return part


def build_score(parts: list[list]) -> stream.Score:
    score = stream.Score()
    for events in parts:
        score.insert(0, build_part(events))
    return score


def write_musicxml(path: Path, parts: list[list]) -> Path:
    build_score(parts).write("musicxml", fp=str(path))
    return path
