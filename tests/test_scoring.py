"""Tests for engine-free run scoring: on-demand compute+cache, and subset runs."""

from __future__ import annotations

from datetime import datetime, timezone

from omrbench import runs, scoring
from omrbench.score.music21_metric import Music21Metric
from tests.helpers import write_musicxml

WHEN = datetime(2026, 6, 19, tzinfo=timezone.utc)
PARTS = [[("N", "C4", 1.0), ("N", "D4", 1.0)]]


def _make_run(tmp_path, sample_ids=("0000",), meta_extra=None):
    corpus = tmp_path / "corpus"
    runs_dir = tmp_path / "runs"
    for sid in sample_ids:
        (corpus / sid).mkdir(parents=True)
        write_musicxml(corpus / sid / "reference.musicxml", PARTS)
    run_dir = runs.create_run_dir("homr", "0.6.1", WHEN, runs_dir=runs_dir)
    for sid in sample_ids:
        write_musicxml(run_dir / "predictions" / f"{sid}.musicxml", PARTS)  # identical -> ser 0
    runs.write_run_meta(run_dir, {"engine": "homr", "corpus": str(corpus), "date": "d", **(meta_extra or {})})
    return runs.load_run(run_dir.name, runs_dir=runs_dir)


def test_ensure_score_computes_caches_and_reuses(tmp_path):
    run = _make_run(tmp_path)
    metric = Music21Metric()
    assert not run.score_path("music21").exists()

    rec = scoring.ensure_score(run, metric)
    assert run.score_path("music21").is_file()          # cached to disk
    assert rec["metric"] == "music21"
    assert rec["summary"]["micro_ser"] == 0.0           # identical pred/ref
    assert rec["summary"]["samples_scored"] == 1

    # second call returns the cached record unchanged
    assert scoring.ensure_score(run, metric) == rec


def test_score_run_marks_missing_prediction_not_ok(tmp_path):
    # corpus has two samples; the engine failed to produce one of them.
    run = _make_run(tmp_path, sample_ids=("0000", "0001"))
    run.prediction("0001").unlink()  # no prediction for 0001

    report = scoring.score_run(run, Music21Metric())
    by = {s.sample_id: s for s in report.samples}
    assert by["0000"].ok is True
    assert by["0001"].ok is False                 # not produced -> not "100% wrong"

    summary = report.to_score_record()["summary"]
    assert summary["samples_total"] == 2
    assert summary["samples_scored"] == 1         # the missing one is excluded, not laundered


def test_score_run_honours_subset_selection(tmp_path):
    # corpus has two samples, but the run declares it only covered 0000
    run = _make_run(tmp_path, sample_ids=("0000", "0001"), meta_extra={"samples": ["0000"]})
    report = scoring.score_run(run, Music21Metric())
    assert [s.sample_id for s in report.samples] == ["0000"]


def test_configured_timeout_reads_scoring_table(tmp_path):
    cfg = tmp_path / "omrbench.toml"
    cfg.write_text("[scoring]\ntimeout = 600\n")
    assert scoring.configured_timeout(cfg) == 600.0


def test_configured_timeout_absent_is_none(tmp_path):
    cfg = tmp_path / "omrbench.toml"
    cfg.write_text('[[engines]]\nengine = "homr"\nversion = "1"\ncmd = "homr"\n')
    assert scoring.configured_timeout(cfg) is None
    assert scoring.configured_timeout(tmp_path / "missing.toml") is None


def test_configured_timeout_rejects_non_positive(tmp_path):
    import pytest

    cfg = tmp_path / "omrbench.toml"
    cfg.write_text("[scoring]\ntimeout = 0\n")
    with pytest.raises(ValueError, match="positive number"):
        scoring.configured_timeout(cfg)


def test_report_from_record_roundtrips(tmp_path):
    # A score computed elsewhere (e.g. a child process) is rebuilt from its
    # record so the CLI can render it — same render as the original report.
    from omrbench.score.report import Report

    run = _make_run(tmp_path, sample_ids=("0000", "0001"))
    metric = Music21Metric()
    original = scoring.score_run(run, metric)
    record = original.to_score_record()
    rebuilt = Report.from_record(record, metric, run.corpus)
    assert rebuilt.render() == original.render()
    assert rebuilt.to_score_record() == record
