# Tier 1 — synthetic corpus

Samples rendered from known-good, **public-domain** MusicXML. Ground truth is
the source MusicXML itself, so it is exact and free, and the rendered image can
have controlled degradations applied.

Layout per sample:

```
<id>/
  image.png            # rendered score (Verovio / LilyPond / MuseScore)
  reference.musicxml   # the source MusicXML = ground truth
  meta.yaml            # source, render engine, degradations, license
```

`meta.yaml`:

```yaml
tier: tier1_synthetic
source: <where the MusicXML came from>
type: synthetic
render_engine: verovio
degradations: []        # e.g. [blur, perspective_warp, jpeg_q40]
license: <public-domain / CC0 / ...>
```

These numbers are **optimistic** relative to real scans — keep them separate
from Tier 2 in any report.
