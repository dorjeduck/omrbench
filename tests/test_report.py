"""Tests for the report: record schema, worst-sample ranking, scored counting."""

from __future__ import annotations

from omrbench.score.base import SampleResult
from omrbench.score.music21_metric import Music21Metric, _fields
from omrbench.score.report import RECORD_SCHEMA_VERSION, Report


def _report():
    return Report(
        metric=Music21Metric(),
        corpus="corpus/tier2_real/polish_scores",
        samples=[
            SampleResult("0000", ok=True, fields=_fields(1, 4)),  # ser 0.25
            SampleResult("0001", ok=True, fields=_fields(3, 4)),  # ser 0.75
            SampleResult("0002", ok=False, fields={}),  # could not be scored
        ],
    )


def test_scored_excludes_not_ok():
    assert [s.sample_id for s in _report().scored] == ["0000", "0001"]


def test_worst_ranked_by_primary_descending():
    worst = _report()._worst()
    assert [s.sample_id for s in worst] == ["0001", "0000"]


def test_to_record_schema_and_counts():
    record = _report().to_record(
        engine="homr",
        engine_version="0.6.0",
        tier="tier2_real",
        date="2026-06-18T00:00:00+00:00",
    )
    assert record["schema_version"] == RECORD_SCHEMA_VERSION
    assert record["engine"] == "homr"
    assert record["engine_version"] == "0.6.0"
    assert record["metric"] == "music21"
    assert record["tier"] == "tier2_real"

    summary = record["summary"]
    assert summary["samples_total"] == 3
    assert summary["samples_scored"] == 2
    # aggregate keys flow straight through from the metric
    assert {"micro_ser", "macro_ser", "median_ser"} <= summary.keys()

    # every sample is recorded, ok flag and fields included, rounded
    assert [s["id"] for s in record["samples"]] == ["0000", "0001", "0002"]
    assert record["samples"][0]["ok"] is True
    assert record["samples"][0]["ser"] == 0.25
    assert record["samples"][2]["ok"] is False


def test_render_contains_headline_and_worst_section():
    text = _report().render()
    assert "metric : music21" in text
    assert "samples: 2 scored / 3 total" in text
    assert "worst samples:" in text
    # primary rendered as a percentage by the metric's format hook
    assert "75.00%" in text
