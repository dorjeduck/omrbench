"""OMR-NED metric (optional) — OMR Normalized Edit Distance, via musicdiff.

This is **musicdiff's OMR-NED**, obtained through musicdiff's documented public
`diff()` API: called with `print_omr_ned_output=True`, `diff()` emits the OMR-NED
report as JSON (OMR edit distance, the symbol counts, and OMR-NED itself, which
musicdiff defines as edit distance / total symbols in both scores). We capture
that JSON and read the values; the metric is entirely musicdiff's.

musicdiff (Greg Chapman's MusicDiff, MIT) is the implementation the Sheet Music
Benchmark paper (https://arxiv.org/abs/2506.10488) builds on. It reads the
MusicXML reference directly.
musicdiff is optional/heavy: install with `pip install -e '.[omr-ned]'`.
"""

from __future__ import annotations

import contextlib
import io
import json
import statistics
from pathlib import Path

from omrbench.score.base import SampleResult, default_format

try:
    import converter21
    import musicdiff
except ImportError as exc:  # pragma: no cover - guidance path
    raise ImportError(
        "the omr-ned metric needs musicdiff; install it with "
        "`pip install -e '.[omr-ned]'`"
    ) from exc

#: ratio fields shown as percentages; symbol counts use default_format
_PERCENT = {"omr_ned", "micro_omr_ned", "macro_omr_ned", "median_omr_ned"}


class OmrNedMetric:
    name = "omr-ned"
    primary = "omr_ned"

    def __init__(self) -> None:
        # musicdiff parses some formats through converter21; harmless for plain
        # MusicXML and idempotent to call.
        converter21.register()

    def format(self, key: str, value: float) -> str:
        if key in _PERCENT:
            return f"{100 * value:.2f}%"
        return default_format(key, value)

    def score(self, prediction: Path, reference: Path, sample_id: str) -> SampleResult:
        # Documented public API: diff() returns the OMR edit distance (None if a
        # file fails to parse) and, with print_omr_ned_output, prints the OMR-NED
        # report as JSON. We capture and read that JSON.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            edit_distance = musicdiff.diff(
                str(prediction),
                str(reference),
                visualize_diffs=False,
                print_omr_ned_output=True,
            )
        if edit_distance is None:
            # A file failed to parse: cannot score this sample.
            return SampleResult(sample_id, ok=False, fields={})
        report = json.loads(out.getvalue())
        return SampleResult(
            sample_id,
            ok=True,
            fields={
                "omr_ned": float(report["OMR-NED"]),
                "edit_distance": int(report["OMR-ED"]),
                "ref_symbols": int(report["numSymbolsInGroundTruth"]),
                "pred_symbols": int(report["numSymbolsInPredicted"]),
            },
        )

    def aggregate(self, results: list[SampleResult]) -> dict[str, float]:
        total_distance = sum(r.fields["edit_distance"] for r in results)
        total_symbols = sum(
            r.fields["ref_symbols"] + r.fields["pred_symbols"] for r in results
        )
        neds = [r.fields["omr_ned"] for r in results]
        return {
            "micro_omr_ned": total_distance / total_symbols if total_symbols else 0.0,
            "macro_omr_ned": sum(neds) / len(neds) if neds else 0.0,
            "median_omr_ned": statistics.median(neds) if neds else 0.0,
        }
