"""OMR-NED metric (optional plugin) — for comparability with OMR literature.

OMR-NED is computed on Humdrum **kern. The reference ships **kern directly
(e.g. polish-scores), so only the engine *output* needs MusicXML -> **kern
conversion. That conversion is the known-fragile step (it is what notes2tone
struggled with), which is exactly why it lives behind this opt-in plugin and is
not the default metric.

Not implemented yet — placeholder so the metric registry and CLI wiring are in
place. Implement `_musicxml_to_kern` (e.g. via verovio or music21 humdrum
export) before enabling.
"""

from __future__ import annotations

from pathlib import Path

from omrbench.score.music21_metric import SampleScore


class OmrNedMetric:
    name = "omr-ned"
    requires_reference = "kern"

    def score(self, prediction: Path, reference: Path, sample_id: str) -> SampleScore:
        raise NotImplementedError(
            "OMR-NED metric is not implemented yet. Needs MusicXML->**kern "
            "conversion of the prediction plus a kern edit-distance. Use "
            "--metric music21 for now."
        )
