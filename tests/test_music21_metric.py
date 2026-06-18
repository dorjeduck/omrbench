"""Tests for the music21 metric: tokenization, per-part scoring, aggregation.

The pure-function tests build music21 streams in memory (no file roundtrip) so
they pin the exact token form and scoring algebra. A few integration tests go
through the real parse path on written MusicXML files.
"""

from __future__ import annotations

from music21 import key, note, stream

from omrbench.score.base import SampleResult, default_format
from omrbench.score.music21_metric import (
    Music21Metric,
    _distance,
    _fields,
    _token_for,
    _tokenize,
    _tokenize_part,
)
from tests.helpers import build_part, build_score, write_musicxml


# --- token form ------------------------------------------------------------


def test_token_for_note_chord_rest():
    from music21 import chord

    assert _token_for(note.Note("C4", quarterLength=1.0)) == "N:C4:1.0"
    assert _token_for(note.Rest(quarterLength=2.0)) == "R:2.0"
    # chord pitches are sorted so input order does not change the token
    c = chord.Chord(["E4", "C4"], quarterLength=1.0)
    assert _token_for(c) == "C:C4.E4:1.0"


def test_tokenize_part_interleaves_keysig_by_offset():
    # key signature at offset 0 precedes the notes it governs
    part = build_part([("K", 2), ("N", "C4", 1.0), ("N", "D4", 1.0)])
    assert _tokenize_part(part) == ["K:2", "N:C4:1.0", "N:D4:1.0"]


def test_tokenize_keysig_after_notes_keeps_musical_order():
    # a key change announced mid-part lands among the notes, not at the tail
    part = stream.Part()
    part.append(note.Note("C4", quarterLength=1.0))
    part.append(key.KeySignature(-1))
    part.append(note.Note("D4", quarterLength=1.0))
    assert _tokenize_part(part) == ["N:C4:1.0", "K:-1", "N:D4:1.0"]


def test_tokenize_keeps_parts_separate():
    score = build_score([[("N", "C4", 1.0)], [("N", "G4", 1.0)]])
    assert _tokenize(score) == [["N:C4:1.0"], ["N:G4:1.0"]]


def test_tokenize_no_parts_treated_as_single_part():
    score = stream.Score()
    score.append(note.Note("C4", quarterLength=1.0))
    assert _tokenize(score) == [["N:C4:1.0"]]


# --- per-part distance pooling --------------------------------------------


def test_distance_identical_is_zero():
    parts = [["a", "b"], ["c", "d"]]
    assert _distance(parts, parts) == (0, 4)


def test_distance_does_not_bleed_across_parts():
    # Merging two staves into one part must NOT cancel out: with a flat stream
    # the prediction below would score 0, but per-part it is fully wrong.
    ref = [["a", "b"], ["c", "d"]]
    merged = [["a", "b", "c", "d"], []]
    assert _distance(merged, ref) == (4, 4)


def test_distance_extra_predicted_part_counts_as_insertions():
    ref = [["a", "b"], ["c", "d"]]
    pred = [["a", "b"], ["c", "d"], ["e"]]
    assert _distance(pred, ref) == (1, 4)


def test_distance_missing_predicted_part_counts_as_deletions():
    ref = [["a", "b"], ["c", "d"]]
    pred = [["a", "b"]]
    assert _distance(pred, ref) == (2, 4)


def test_fields_ser_is_distance_over_reference_length():
    assert _fields(1, 4) == {"distance": 1, "reference_length": 4, "ser": 0.25}
    # empty reference: ser defined as 0.0, not a division error
    assert _fields(0, 0)["ser"] == 0.0


# --- aggregation -----------------------------------------------------------


def test_aggregate_micro_macro_median():
    results = [
        SampleResult("0", ok=True, fields=_fields(1, 4)),  # ser 0.25
        SampleResult("1", ok=True, fields=_fields(3, 6)),  # ser 0.5
    ]
    summary = Music21Metric().aggregate(results)
    assert summary["micro_ser"] == (1 + 3) / (4 + 6)
    assert summary["macro_ser"] == (0.25 + 0.5) / 2
    assert summary["median_ser"] == 0.375


def test_aggregate_empty_is_zero_not_error():
    summary = Music21Metric().aggregate([])
    assert summary == {"micro_ser": 0.0, "macro_ser": 0.0, "median_ser": 0.0}


# --- format ----------------------------------------------------------------


def test_format_ratios_as_percent_counts_as_ints():
    m = Music21Metric()
    assert m.format("ser", 0.25) == "25.00%"
    assert m.format("micro_ser", 0.4) == "40.00%"
    assert m.format("distance", 3.0) == default_format("distance", 3.0) == "3"


# --- integration through the real parse path -------------------------------


def test_score_identical_files_is_zero(tmp_path):
    parts = [[("N", "C4", 1.0), ("N", "D4", 1.0)], [("N", "G3", 2.0)]]
    ref = write_musicxml(tmp_path / "ref.musicxml", parts)
    pred = write_musicxml(tmp_path / "pred.musicxml", parts)
    result = Music21Metric().score(pred, ref, "0")
    assert result.ok is True
    assert result.fields["ser"] == 0.0


def test_score_unparseable_prediction_is_full_error(tmp_path):
    ref = write_musicxml(tmp_path / "ref.musicxml", [[("N", "C4", 1.0)]])
    pred = tmp_path / "pred.musicxml"
    pred.write_text("this is not musicxml")
    result = Music21Metric().score(pred, ref, "0")
    assert result.ok is True
    assert result.fields["ser"] == 1.0


def test_score_unparseable_reference_is_not_ok(tmp_path):
    ref = tmp_path / "ref.musicxml"
    ref.write_text("this is not musicxml")
    pred = write_musicxml(tmp_path / "pred.musicxml", [[("N", "C4", 1.0)]])
    result = Music21Metric().score(pred, ref, "0")
    assert result.ok is False
    assert result.fields == {}
