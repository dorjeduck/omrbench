"""Scoring-job validation: a progress/cancel request must validate the metric
*name* without instantiating it, so an opt-in metric whose extra isn't installed
(e.g. omr-ned needs musicdiff) reports cleanly instead of 500-ing on ImportError.
"""

from __future__ import annotations

import sys

import pytest

from omrbench.server import jobs


def test_require_known_accepts_optin_metric_without_importing(monkeypatch):
    # Simulate musicdiff not installed: importing omr-ned's module must NOT happen
    # during name validation. Poison the import so it would fail if attempted.
    monkeypatch.setitem(sys.modules, "musicdiff", None)
    jobs._require_known("music21")
    jobs._require_known("omr-ned")  # known by name; no instantiation, no import


def test_require_known_rejects_unknown():
    with pytest.raises(KeyError):
        jobs._require_known("definitely-not-a-metric")
