"""Scoring. Operates purely on MusicXML; imports no OMR engine, so results are
comparable across any tool that emits MusicXML.

Metrics are registered by name in REGISTRY as zero-arg factories. Factories
(not classes) so a metric with optional/heavy dependencies imports them only
when actually selected. Adding a metric is: write a class satisfying
`omrbench.score.base.Metric`, add one line here.
"""

from omrbench.score.base import Metric, SampleResult


def _music21() -> Metric:
    from omrbench.score.music21_metric import Music21Metric

    return Music21Metric()


def _omr_ned() -> Metric:
    from omrbench.score.omr_ned import OmrNedMetric

    return OmrNedMetric()


REGISTRY = {
    "music21": _music21,
    "omr-ned": _omr_ned,
}


def get_metric(name: str) -> Metric:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown metric {name!r}; known metrics: {known}")
    return REGISTRY[name]()


__all__ = ["Metric", "SampleResult", "REGISTRY", "get_metric"]
