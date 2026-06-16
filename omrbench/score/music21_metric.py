"""Default metric: note/symbol-level normalized edit distance over MusicXML.

Both prediction and reference are parsed with music21, flattened to a single
ordered token stream (key signatures, notes, chords, rests), and compared with
Levenshtein distance. The score is SER = edit_distance / len(reference_tokens),
so 0.0 is perfect and lower is better.

Deliberately format-only: no engine vocabulary, no **kern step. The token form
is documented so other tools' output is scored identically.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import editdistance
from music21 import chord, converter, key, note, stream

from omrbench.score.base import SampleResult, default_format


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


def _fields(distance: int, reference_length: int) -> dict[str, float]:
    ser = distance / reference_length if reference_length else 0.0
    return {"distance": distance, "reference_length": reference_length, "ser": ser}


#: ratio fields shown as percentages; other fields (counts) use default_format
_PERCENT = {"ser", "micro_ser", "macro_ser", "median_ser"}


class Music21Metric:
    name = "music21"
    primary = "ser"

    def format(self, key: str, value: float) -> str:
        if key in _PERCENT:
            return f"{100 * value:.2f}%"
        return default_format(key, value)

    def score(self, prediction: Path, reference: Path, sample_id: str) -> SampleResult:
        try:
            ref_tokens = tokenize_file(reference)
        except Exception:
            return SampleResult(sample_id, ok=False, fields={})
        try:
            pred_tokens = tokenize_file(prediction)
        except Exception:
            # Engine produced unparseable / no output: count full reference as wrong.
            n = len(ref_tokens)
            return SampleResult(sample_id, ok=True, fields=_fields(n, n))
        distance = editdistance.eval(pred_tokens, ref_tokens)
        return SampleResult(sample_id, ok=True, fields=_fields(distance, len(ref_tokens)))

    def aggregate(self, results: list[SampleResult]) -> dict[str, float]:
        # Micro: pooled distance over pooled reference length. Macro/median: over
        # per-sample SER.
        total_distance = sum(r.fields["distance"] for r in results)
        total_length = sum(r.fields["reference_length"] for r in results)
        sers = [r.fields["ser"] for r in results]
        return {
            "micro_ser": total_distance / total_length if total_length else 0.0,
            "macro_ser": sum(sers) / len(sers) if sers else 0.0,
            "median_ser": statistics.median(sers) if sers else 0.0,
        }
