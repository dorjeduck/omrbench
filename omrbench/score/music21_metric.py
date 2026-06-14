"""Default metric: note/symbol-level normalized edit distance over MusicXML.

Both prediction and reference are parsed with music21, flattened to a single
ordered token stream (key signatures, notes, chords, rests), and compared with
Levenshtein distance. The score is SER = edit_distance / len(reference_tokens),
so 0.0 is perfect and lower is better.

Deliberately format-only: no engine vocabulary, no **kern step. The token form
is documented so other tools' output is scored identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import editdistance
from music21 import chord, converter, key, note, stream


def _tokenize(score: stream.Score) -> list[str]:
    tokens: list[str] = []
    # Sort parts for determinism, then read each part in document order.
    for part in score.parts:
        for element in part.recurse().notesAndRests:
            tokens.append(_token_for(element))
        for ks in part.recurse().getElementsByClass(key.KeySignature):
            tokens.append(f"K:{ks.sharps}")
    return tokens


def _token_for(element: object) -> str:
    if isinstance(element, note.Note):
        return f"N:{element.pitch.nameWithOctave}:{element.duration.quarterLength}"
    if isinstance(element, chord.Chord):
        pitches = ".".join(sorted(p.nameWithOctave for p in element.pitches))
        return f"C:{pitches}:{element.duration.quarterLength}"
    if isinstance(element, note.Rest):
        return f"R:{element.duration.quarterLength}"
    return f"?:{type(element).__name__}"


def tokenize_file(path: Path) -> list[str]:
    score = converter.parse(str(path))
    if isinstance(score, stream.Score):
        return _tokenize(score)
    # Some parses return a flat Stream; wrap it.
    wrapped = stream.Score()
    wrapped.append(score)
    return _tokenize(wrapped)


@dataclass
class SampleScore:
    sample_id: str
    distance: int
    reference_length: int
    ok: bool

    @property
    def ser(self) -> float:
        if self.reference_length == 0:
            return 0.0
        return self.distance / self.reference_length


class Music21Metric:
    name = "music21"
    requires_reference = "musicxml"

    def score(self, prediction: Path, reference: Path, sample_id: str) -> SampleScore:
        try:
            ref_tokens = tokenize_file(reference)
        except Exception:
            return SampleScore(sample_id, 0, 0, ok=False)
        try:
            pred_tokens = tokenize_file(prediction)
        except Exception:
            # Engine produced unparseable / no output: count full reference as wrong.
            return SampleScore(sample_id, len(ref_tokens), len(ref_tokens), ok=True)
        distance = editdistance.eval(pred_tokens, ref_tokens)
        return SampleScore(sample_id, distance, len(ref_tokens), ok=True)
