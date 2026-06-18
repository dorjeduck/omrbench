"""Default metric: note/symbol-level normalized edit distance over MusicXML.

Both prediction and reference are parsed with music21 and turned into one ordered
token stream *per part* (key signatures, notes, chords, rests, each at its place
in the part by musical offset). Corresponding parts are aligned by index and
compared with Levenshtein distance; the per-part distances are pooled. The score
is SER = total_edit_distance / total_reference_tokens, so 0.0 is perfect and
lower is better.

Why per part, not one flat stream: concatenating every staff into a single
sequence lets one part's tokens cancel against another's, so an engine that
merges two staves into one (or emits them in a different order) could score
better or worse for reasons unrelated to recognition. Keeping parts separate and
aligning them by document position scores each staff on its own terms. The
correspondence is positional — reference part *i* against prediction part *i*; a
missing or extra predicted part is counted as pure deletion/insertion against the
reference part at that index.

Deliberately format-only: no engine vocabulary, no **kern step. The token form
is documented so other tools' output is scored identically.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import editdistance
from music21 import chord, converter, key, note, stream

from omrbench.score.base import SampleResult, default_format


def _tokenize_part(part: stream.Stream) -> list[str]:
    # Flatten so offsets are absolute within the part, then emit notes/rests and
    # key signatures interleaved in musical order. At a shared offset a key
    # signature precedes the notes it governs (priority 0 before 1).
    flat = part.flatten()
    events: list[tuple[float, int, str]] = []
    for element in flat.notesAndRests:
        events.append((float(element.offset), 1, _token_for(element)))
    for ks in flat.getElementsByClass(key.KeySignature):
        events.append((float(ks.offset), 0, f"K:{ks.sharps}"))
    events.sort(key=lambda e: (e[0], e[1]))
    return [token for _, _, token in events]


def _tokenize(score: stream.Score) -> list[list[str]]:
    """One token list per part, in document order. A parse with no parts (a flat
    stream) is treated as a single part."""
    parts = list(score.parts)
    if not parts:
        return [_tokenize_part(score)]
    return [_tokenize_part(part) for part in parts]


def _token_for(element: object) -> str:
    if isinstance(element, note.Note):
        return f"N:{element.pitch.nameWithOctave}:{element.duration.quarterLength}"
    if isinstance(element, chord.Chord):
        pitches = ".".join(sorted(p.nameWithOctave for p in element.pitches))
        return f"C:{pitches}:{element.duration.quarterLength}"
    if isinstance(element, note.Rest):
        return f"R:{element.duration.quarterLength}"
    return f"?:{type(element).__name__}"


def tokenize_file(path: Path) -> list[list[str]]:
    """Parse a MusicXML file into one token list per part."""
    score = converter.parse(str(path))
    if isinstance(score, stream.Score):
        return _tokenize(score)
    # Some parses return a flat Stream; treat it as a single part.
    return [_tokenize_part(score)]


def _distance(pred_parts: list[list[str]], ref_parts: list[list[str]]) -> tuple[int, int]:
    """Pooled edit distance and reference length over index-aligned parts. A
    part present on only one side is compared against an empty list, so it
    contributes pure insertions or deletions."""
    total = 0
    for i in range(max(len(pred_parts), len(ref_parts))):
        pred = pred_parts[i] if i < len(pred_parts) else []
        ref = ref_parts[i] if i < len(ref_parts) else []
        total += editdistance.eval(pred, ref)
    reference_length = sum(len(ref) for ref in ref_parts)
    return total, reference_length


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
            ref_parts = tokenize_file(reference)
        except Exception:
            return SampleResult(sample_id, ok=False, fields={})
        try:
            pred_parts = tokenize_file(prediction)
        except Exception:
            # Engine produced unparseable / no output: count full reference as wrong.
            n = sum(len(ref) for ref in ref_parts)
            return SampleResult(sample_id, ok=True, fields=_fields(n, n))
        distance, reference_length = _distance(pred_parts, ref_parts)
        return SampleResult(sample_id, ok=True, fields=_fields(distance, reference_length))

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
