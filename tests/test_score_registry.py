"""Tests for the metric registry: name lookup and unknown-metric errors."""

from __future__ import annotations

import pytest

from omrbench.score import REGISTRY, get_metric
from omrbench.score.music21_metric import Music21Metric


def test_get_metric_music21_returns_instance():
    metric = get_metric("music21")
    assert isinstance(metric, Music21Metric)
    assert metric.name == "music21"
    assert metric.primary == "ser"


def test_registry_lists_both_metrics():
    assert set(REGISTRY) == {"music21", "omr-ned"}


def test_get_metric_unknown_raises_with_known_list():
    with pytest.raises(KeyError) as exc:
        get_metric("nope")
    # the message names the metrics that are known, to guide the caller
    assert "music21" in str(exc.value)
