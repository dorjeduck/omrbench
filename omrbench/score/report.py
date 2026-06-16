"""Aggregate per-sample results into a report. The report is metric-agnostic:
the headline numbers come from `metric.aggregate`, and worst-sample ranking
uses the metric's declared `primary` field, so no metric is special-cased here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omrbench.score.base import Metric, SampleResult, default_format

#: bump when the persisted result-record shape changes incompatibly
RECORD_SCHEMA_VERSION = 1


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

    def _worst(self, n: int = 10) -> list[SampleResult]:
        key = self.metric.primary
        return sorted(self.scored, key=lambda s: s.fields.get(key, 0.0), reverse=True)[:n]

    def to_record(
        self,
        engine: str,
        engine_version: str | None,
        tier: str | None,
        date: str,
    ) -> dict:
        """A self-describing result record: metadata + aggregates + every
        per-sample result, so history/comparison/worst-N are views over JSON
        with no re-run. Imports no engine."""
        return {
            "schema_version": RECORD_SCHEMA_VERSION,
            "engine": engine,
            "engine_version": engine_version,
            "metric": self.metric.name,
            "corpus": self.corpus,
            "tier": tier,
            "date": date,
            "summary": {
                "samples_total": len(self.samples),
                "samples_scored": len(self.scored),
                **{k: round(v, 6) for k, v in self.summary.items()},
            },
            "samples": [
                {
                    "id": s.sample_id,
                    "ok": s.ok,
                    **{k: round(v, 6) for k, v in s.fields.items()},
                }
                for s in self.samples
            ],
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
        lines += ["", "worst samples:"]
        primary = self.metric.primary
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
