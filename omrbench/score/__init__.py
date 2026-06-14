"""Scoring. Operates purely on MusicXML (and optionally **kern); imports no
OMR engine, so results are comparable across any tool that emits MusicXML."""

from omrbench.score.music21_metric import Music21Metric

REGISTRY = {
    "music21": Music21Metric,
}


def get_metric(name: str):
    if name == "omr-ned":
        from omrbench.score.omr_ned import OmrNedMetric

        return OmrNedMetric()
    if name not in REGISTRY:
        known = ", ".join([*sorted(REGISTRY), "omr-ned"])
        raise KeyError(f"unknown metric {name!r}; known metrics: {known}")
    return REGISTRY[name]()
