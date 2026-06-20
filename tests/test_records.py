"""Tests for the runs read layer: comparable-run selection."""

from __future__ import annotations

from datetime import datetime, timezone

from omrbench import records, runs


def _make_run(engine, when, corpus, ids):
    run_dir = runs.create_run_dir(engine, "1.0", when)  # default runs_dir = ./runs (cwd)
    for sid in ids:
        (run_dir / "predictions" / f"{sid}.musicxml").write_text("<x/>")
    runs.write_run_meta(run_dir, {"engine": engine, "corpus": corpus, "date": when.isoformat()})
    return run_dir.name


def test_comparable_runs_same_corpus_and_overlapping_samples(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # RUNS_DIR is the relative ./runs
    t = lambda d: datetime(2026, 1, d, tzinfo=timezone.utc)

    a = _make_run("homr", t(1), "corpus/C", ["0000", "0001"])
    b = _make_run("homr", t(2), "corpus/C", ["0001", "0002"])   # shares 0001 with a
    _make_run("homr", t(3), "corpus/OTHER", ["0000"])           # different corpus -> excluded
    _make_run("homr", t(4), "corpus/C", ["0009"])               # same corpus, no overlap -> excluded

    comparable = [r.run_id for r in records.comparable_runs(a)]
    assert comparable == [b]


def test_comparable_runs_excludes_self_and_handles_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    only = _make_run("homr", datetime(2026, 1, 1, tzinfo=timezone.utc), "corpus/C", ["0000"])
    assert records.comparable_runs(only) == []  # nothing else to compare with
