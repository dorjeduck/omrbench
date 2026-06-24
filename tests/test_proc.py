"""The central process toolkit (omrbench/proc.py): command runner + killable
job, both bounded by a wall-clock budget."""

from __future__ import annotations

import time

import pytest

from omrbench.proc import Job, run_blocking, run_command


# --- run_command (shell out) -----------------------------------------------

def test_run_command_times_out():
    # A command that outlives its budget has its tree killed and fails the
    # sample, instead of freezing the run.
    assert run_command(["sleep", "5"], timeout=0.2) is False
    assert run_command(["true"], timeout=5) is True


def test_run_command_missing_binary_is_false():
    assert run_command(["definitely-not-a-real-binary-xyz"]) is False


# --- Job / run_blocking (python worker in a killable child) ----------------

def _sleep_worker(progress, seconds):
    time.sleep(seconds)


def _returning_worker(progress):
    progress(1, 1)
    return {"answer": 42}


def _failing_worker(progress):
    raise ValueError("boom")


def test_run_blocking_returns_worker_value():
    seen = []
    result = run_blocking(_returning_worker, timeout=5,
                          on_progress=lambda d, t: seen.append((d, t)))
    assert result == {"answer": 42}
    assert seen == [(1, 1)]


def test_run_blocking_times_out():
    with pytest.raises(TimeoutError):
        run_blocking(_sleep_worker, (30,), timeout=0.2)


def test_run_blocking_surfaces_worker_error():
    with pytest.raises(RuntimeError, match="boom"):
        run_blocking(_failing_worker)


def _shell_sleep_worker(progress):
    # A worker that shells out, mirroring an engine run inside a Job.
    run_command(["sleep", "31.4159"])


def _pgrep(pattern):
    import subprocess
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [p for p in out.stdout.split() if p]


def test_kill_reaps_shelled_out_command_tree():
    # The crux: a Job's group-kill must also reap a command the worker shelled
    # out to, even though the command runs in its own session.
    job = Job(_shell_sleep_worker)
    job.start()
    end = time.monotonic() + 5
    while time.monotonic() < end and not _pgrep("31.4159"):
        time.sleep(0.02)
    assert _pgrep("31.4159"), "command did not start"
    job.kill()
    end = time.monotonic() + 5
    while time.monotonic() < end and _pgrep("31.4159"):
        time.sleep(0.02)
    assert not _pgrep("31.4159"), "command tree leaked after kill"


def test_job_timeout_reports_and_dies():
    job = Job(_sleep_worker, args=(30,), timeout=0.2)
    job.start()
    msgs = []
    end = time.monotonic() + 5
    while time.monotonic() < end:
        msgs.extend(job.drain())
        if not job.alive():
            msgs.extend(job.drain())
            break
        time.sleep(0.02)
    assert not job.alive()
    assert job.timed_out
    assert any(m[0] == "error" and "time budget" in m[1] for m in msgs)
