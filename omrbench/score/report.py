"""Aggregate per-sample results into a report. The report is metric-agnostic:
the headline numbers come from `metric.aggregate`, and worst-sample ranking
uses the metric's declared `primary` field, so no metric is special-cased here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omrbench.score.base import Metric, SampleResult, default_format

#: bump when the persisted result-record shape changes incompatibly
RECORD_SCHEMA_VERSION = 1


def _percentile(values_sorted: list[float], q: float) -> float:
    """Linear-interpolated percentile of a pre-sorted list (``q`` in [0, 1])."""
    if not values_sorted:
        return 0.0
    if len(values_sorted) == 1:
        return values_sorted[0]
    pos = q * (len(values_sorted) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(values_sorted) - 1)
    return values_sorted[lo] + (values_sorted[hi] - values_sorted[lo]) * (pos - lo)


@dataclass
class Report:
    metric: Metric
    corpus: str
    samples: list[SampleResult] = field(default_factory=list)

    @property
    def scored(self) -> list[SampleResult]:
        return [s for s in self.samples if s.ok]

    @property
    def summary(self) -> dict[str, float]:
        return self.metric.aggregate(self.scored)

    @property
    def distribution(self) -> dict[str, float]:
        """Spread of the primary field across scored samples. Since lower is
        better, the high tail (p90/p95/max) is where the failures live; iqr is
        the middle spread. Computed generically over any metric's `primary`, and
        keyed `<stat>_<primary>` to match the metric's own aggregate keys (so the
        report and web UI format and trend them the same way)."""
        primary = self.metric.primary
        values = sorted(s.fields.get(primary, 0.0) for s in self.scored)
        if not values:
            return {}
        return {
            f"p90_{primary}": _percentile(values, 0.90),
            f"p95_{primary}": _percentile(values, 0.95),
            f"max_{primary}": values[-1],
            f"iqr_{primary}": _percentile(values, 0.75) - _percentile(values, 0.25),
        }

    def _worst(self, n: int = 10) -> list[SampleResult]:
        key = self.metric.primary
        return sorted(self.scored, key=lambda s: s.fields.get(key, 0.0), reverse=True)[:n]

    def _summary_dict(self) -> dict:
        return {
            "samples_total": len(self.samples),
            "samples_scored": len(self.scored),
            **{k: round(v, 6) for k, v in self.summary.items()},
            **{k: round(v, 6) for k, v in self.distribution.items()},
        }

    def _samples_list(self) -> list[dict]:
        return [
            {"id": s.sample_id, "ok": s.ok, **{k: round(v, 6) for k, v in s.fields.items()}}
            for s in self.samples
        ]

    @classmethod
    def from_record(cls, record: dict, metric: Metric, corpus: str) -> "Report":
        """Rebuild a Report from a persisted score record (the inverse of
        `to_score_record`), so a score computed elsewhere — e.g. in a child
        process — can still be rendered. Aggregates recompute from the per-sample
        fields, matching the stored summary."""
        report = cls(metric=metric, corpus=corpus)
        for s in record.get("samples", []):
            fields = {k: v for k, v in s.items() if k not in ("id", "ok")}
            report.samples.append(SampleResult(s["id"], ok=s["ok"], fields=fields))
        return report

    def to_score_record(self) -> dict:
        """The cached score for one run+metric (`runs/<run-id>/scores/<metric>.json`).
        Carries only what is metric-specific — aggregates + every per-sample
        result; the run-level metadata (engine, corpus, date) lives in `run.json`,
        not here."""
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "metric": self.metric.name,
            "summary": self._summary_dict(),
            "samples": self._samples_list(),
        }

    def render(self) -> str:
        fmt = getattr(self.metric, "format", default_format)
        lines = [
            f"corpus : {self.corpus}",
            f"metric : {self.metric.name}",
            f"samples: {len(self.scored)} scored / {len(self.samples)} total",
        ]
        for key, value in self.summary.items():
            lines.append(f"{key}: {fmt(key, value)}")
        primary = self.metric.primary
        dist = self.distribution
        if dist:
            # values are of the primary field, so format them in its unit
            spread = "  ".join(f"{k} {fmt(primary, v)}" for k, v in dist.items())
            lines.append(f"spread : {spread}")
        lines += ["", "worst samples:"]
        for s in self._worst():
            head = f"{primary} {fmt(primary, s.fields.get(primary, 0.0))}"
            detail = "  ".join(
                f"{k} {fmt(k, v)}" for k, v in s.fields.items() if k != primary
            )
            line = f"  {s.sample_id:<24} {head}"
            if detail:
                line += f"  ({detail})"
            lines.append(line)
        return "\n".join(lines)
