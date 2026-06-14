"""Aggregate per-sample scores into a report. Micro-SER (pooled distance over
pooled reference length) is the headline number; macro is the per-sample mean."""

from __future__ import annotations

from dataclasses import dataclass, field

from omrbench.score.music21_metric import SampleScore


@dataclass
class Report:
    metric: str
    corpus: str
    samples: list[SampleScore] = field(default_factory=list)

    @property
    def scored(self) -> list[SampleScore]:
        return [s for s in self.samples if s.ok]

    @property
    def micro_ser(self) -> float:
        total_len = sum(s.reference_length for s in self.scored)
        if total_len == 0:
            return 0.0
        return sum(s.distance for s in self.scored) / total_len

    @property
    def macro_ser(self) -> float:
        scored = self.scored
        if not scored:
            return 0.0
        return sum(s.ser for s in scored) / len(scored)

    def render(self) -> str:
        lines = [
            f"corpus : {self.corpus}",
            f"metric : {self.metric}",
            f"samples: {len(self.scored)} scored / {len(self.samples)} total",
            f"micro-SER: {100 * self.micro_ser:.2f}%",
            f"macro-SER: {100 * self.macro_ser:.2f}%",
            "",
            "worst samples:",
        ]
        worst = sorted(self.scored, key=lambda s: s.ser, reverse=True)[:10]
        for s in worst:
            lines.append(f"  {s.sample_id:<24} SER {100 * s.ser:6.2f}%  ({s.distance}/{s.reference_length})")
        return "\n".join(lines)
