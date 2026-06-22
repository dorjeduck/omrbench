"""Tests for the report: record schema, worst-sample ranking, scored counting."""

from __future__ import annotations

from omrbench.score.base import SampleResult
from omrbench.score.music21_metric import Music21Metric, _fields
from omrbench.score.report import RECORD_SCHEMA_VERSION, Report


def _report():
    return Report(
        metric=Music21Metric(),
        corpus="corpus/real/polish_scores",
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
        kind="real",
        date="2026-06-18T00:00:00+00:00",
    )
    assert record["schema_version"] == RECORD_SCHEMA_VERSION
    assert record["engine"] == "homr"
    assert record["engine_version"] == "0.6.0"
    assert record["metric"] == "music21"
    assert record["kind"] == "real"

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


def _spread_report(sers):
    return Report(
        metric=Music21Metric(),
        corpus="c",
        samples=[
            SampleResult(f"{i:04d}", ok=True, fields=_fields(int(s * 4), 4))
            for i, s in enumerate(sers)
        ],
    )


def test_distribution_percentiles_over_primary():
    dist = _spread_report([0.0, 0.25, 0.5, 0.75, 1.0]).distribution
    assert dist == {
        "p90_ser": 0.90,
        "p95_ser": 0.95,
        "max_ser": 1.0,
        "iqr_ser": 0.5,  # p75 (0.75) - p25 (0.25)
    }


def test_distribution_empty_when_nothing_scored():
    report = Report(
        metric=Music21Metric(),
        corpus="c",
        samples=[SampleResult("0000", ok=False, fields={})],
    )
    assert report.distribution == {}
    # render must not crash with no scored samples
    assert "spread" not in report.render()


def test_to_record_includes_spread_keys():
    summary = _spread_report([0.0, 0.5, 1.0]).to_record("e", None, None, "d")["summary"]
    assert {"p90_ser", "p95_ser", "max_ser", "iqr_ser"} <= summary.keys()
    assert summary["max_ser"] == 1.0


def test_to_score_record_is_run_free():
    # the cached score (runs/<id>/scores/<metric>.json) carries only metric data;
    # run-level metadata (engine, corpus, date) lives in run.json, not here
    record = _report().to_score_record()
    assert set(record) == {"schema_version", "metric", "summary", "samples"}
    assert record["metric"] == "music21"
    assert record["summary"]["samples_scored"] == 2
    assert [s["id"] for s in record["samples"]] == ["0000", "0001", "0002"]


def test_render_shows_spread_line_as_percent():
    text = _spread_report([0.0, 0.5, 1.0]).render()
    assert "spread :" in text
    assert "max_ser 100.00%" in text
