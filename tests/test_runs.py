"""Tests for the runs storage layer: run-id, run dir creation, read/write."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from omrbench.runs import (
    Run,
    create_run_dir,
    list_runs,
    load_run,
    make_run_id,
    write_run_meta,
)

WHEN = datetime(2026, 6, 19, 8, 30, 12, tzinfo=timezone.utc)


def test_make_run_id_engine_version_timestamp():
    assert make_run_id("homr", "0.6.1", WHEN) == "homr-0.6.1-20260619T083012Z"


def test_make_run_id_sanitizes_verbose_version():
    # a git-describe version is kept but made path-safe
    assert make_run_id("homr", "v0.6.2-54-g83074e1", WHEN) == "homr-v0.6.2-54-g83074e1-20260619T083012Z"


def test_create_run_dir_makes_predictions_dir(tmp_path):
    run_dir = create_run_dir("homr", "0.6.1", WHEN, runs_dir=tmp_path)
    assert run_dir == tmp_path / "homr-0.6.1-20260619T083012Z"
    assert (run_dir / "predictions").is_dir()


def test_create_run_dir_collision_gets_suffix(tmp_path):
    first = create_run_dir("homr", "0.6.1", WHEN, runs_dir=tmp_path)
    second = create_run_dir("homr", "0.6.1", WHEN, runs_dir=tmp_path)
    third = create_run_dir("homr", "0.6.1", WHEN, runs_dir=tmp_path)
    assert first.name == "homr-0.6.1-20260619T083012Z"
    assert second.name == "homr-0.6.1-20260619T083012Z-b"
    assert third.name == "homr-0.6.1-20260619T083012Z-c"


def test_write_and_load_run_roundtrip(tmp_path):
    run_dir = create_run_dir("homr", "0.6.1", WHEN, runs_dir=tmp_path)
    meta = {"engine": "homr", "engine_version": "0.6.1", "corpus": "polish_scores", "date": WHEN.isoformat()}
    write_run_meta(run_dir, meta)

    run = load_run("homr-0.6.1-20260619T083012Z", runs_dir=tmp_path)
    assert run.engine == "homr"
    assert run.engine_version == "0.6.1"
    assert run.corpus == "polish_scores"
    assert run.samples is None  # full-corpus run omits the field
    assert run.prediction("0000") == run_dir / "predictions" / "0000.musicxml"
    assert run.score_path("music21") == run_dir / "scores" / "music21.json"


def test_load_run_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_run("nope", runs_dir=tmp_path)


def test_samples_field_present_on_subset_run(tmp_path):
    run_dir = create_run_dir("homr", "0.6.1", WHEN, runs_dir=tmp_path)
    write_run_meta(run_dir, {"engine": "homr", "corpus": "c", "date": "d", "samples": ["0000", "0001"]})
    run = load_run(run_dir.name, runs_dir=tmp_path)
    assert run.samples == ["0000", "0001"]


def test_list_runs_newest_first_ignores_non_runs(tmp_path):
    a = create_run_dir("homr", "0.6.1", datetime(2026, 1, 1, tzinfo=timezone.utc), runs_dir=tmp_path)
    b = create_run_dir("audiveris", "5.10", datetime(2026, 3, 1, tzinfo=timezone.utc), runs_dir=tmp_path)
    write_run_meta(a, {"engine": "homr", "date": "2026-01-01T00:00:00+00:00"})
    write_run_meta(b, {"engine": "audiveris", "date": "2026-03-01T00:00:00+00:00"})
    (tmp_path / "loose.txt").write_text("ignored")
    (tmp_path / "no-meta").mkdir()  # dir without run.json is skipped

    runs = list_runs(runs_dir=tmp_path)
    assert [r.run_id for r in runs] == [b.name, a.name]  # newest (March) first
    assert all(isinstance(r, Run) for r in runs)
