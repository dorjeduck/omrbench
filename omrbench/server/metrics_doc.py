"""Human-readable descriptions of the metrics — display text only.

This is presentation copy, so it lives in the server package, not in the metric
classes: the scoring core stays unaware of how its numbers are explained. Keyed
by metric `name` (the same key as `score.REGISTRY`); a metric without an entry
here still appears in the catalog with an empty description.
"""

from __future__ import annotations

#: metric name -> {title, summary, fields, notes}
DESCRIPTIONS: dict[str, dict] = {
    "music21": {
        "primary": "ser",
        "title": "music21 SER — symbol-level edit distance",
        "summary": (
            "Both the prediction and the reference MusicXML are parsed with "
            "music21 and flattened into one ordered token stream — key "
            "signatures, notes, chords and rests — then compared with "
            "Levenshtein (edit) distance. The per-sample score is "
            "SER = edit_distance / reference_token_count, so 0.0 is perfect and "
            "lower is better. It is deliberately format-only: no engine "
            "vocabulary and no **kern step, so any tool emitting MusicXML is "
            "scored identically."
        ),
        "fields": {
            "ser": "this sample's SER (edit distance / reference length)",
            "distance": "raw token edit distance",
            "reference_length": "number of reference tokens",
        },
        "aggregates": {
            "micro_ser": "pooled distance over pooled reference length (size-weighted)",
            "macro_ser": "mean of per-sample SER (every sample weighted equally)",
            "median_ser": "median of per-sample SER (robust to outliers)",
        },
        "notes": "Default metric. Lightweight; core dependency.",
    },
    "omr-ned": {
        "primary": "omr_ned",
        "title": "OMR-NED — via musicdiff",
        "summary": (
            "musicdiff's OMR Normalized Edit Distance, computed by musicdiff "
            "(Greg Chapman's MusicDiff, MIT) directly on the parsed MusicXML. "
            "OMR-NED is defined as edit_distance / (symbols in both scores) = "
            "(I + D) / (N1 + N2). It is the implementation the Sheet Music "
            "Benchmark paper builds on; the numbers are musicdiff's own, not "
            "guaranteed paper-identical."
        ),
        "fields": {
            "omr_ned": "this sample's OMR-NED",
            "edit_distance": "musicdiff OMR edit distance (OMR-ED)",
            "ref_symbols": "symbols in the ground-truth score",
            "pred_symbols": "symbols in the predicted score",
        },
        "aggregates": {
            "micro_omr_ned": "pooled edit distance over pooled symbol count",
            "macro_omr_ned": "mean of per-sample OMR-NED",
            "median_omr_ned": "median of per-sample OMR-NED",
        },
        "notes": (
            "Opt-in (`.[omr-ned]` extra); musicdiff is heavy and slow, hence "
            "not installed by default."
        ),
    },
}
