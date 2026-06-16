"""The metric contract — the single seam every metric plugs into.

A metric is a small strategy object with two jobs: score one prediction against
one reference (`score`), and roll the per-sample results up into summary numbers
(`aggregate`). Everything else — corpus discovery, the CLI, the report, the
persisted JSON record — is metric-agnostic and goes through this contract, so
adding a metric is "write a class, register it" with no change to the core.

Each metric owns the *shape* of its own numbers. `SampleResult.fields` is an
open dict of named per-sample values (a `ser`, an `omr_ned`, an `f1`, whatever),
and `aggregate` returns whatever summary keys the metric defines. The only thing
the core assumes about any metric is `primary`: the name of the one field, with
lower meaning better, used for ranking worst samples and taking medians.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class SampleResult:
    sample_id: str
    ok: bool
    #: named per-sample numbers; keys are defined by the metric. Empty when the
    #: sample could not be scored (ok=False).
    fields: dict[str, float]


@runtime_checkable
class Metric(Protocol):
    #: registry key and report label
    name: str
    #: key in SampleResult.fields used for ranking and medians (lower = better)
    primary: str

    def score(self, prediction: Path, reference: Path, sample_id: str) -> SampleResult:
        ...

    def aggregate(self, results: list[SampleResult]) -> dict[str, float]:
        """Summary numbers over the results that scored ok. Keys are the
        metric's own (e.g. micro_ser/macro_ser); they flow straight into the
        report and the persisted record."""
        ...

    def format(self, key: str, value: float) -> str:
        """Human-readable rendering of one named number (a summary key or a
        SampleResult field) for the console report. Optional: the report falls
        back to `default_format` if a metric omits it. This is where a metric
        says "my ratios are percentages, my counts are integers" — keeping that
        unit knowledge with the metric instead of in the shared report."""
        ...


def default_format(key: str, value: float) -> str:
    """Unit-agnostic fallback: integers as integers, everything else as a
    fixed-precision decimal."""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}"
