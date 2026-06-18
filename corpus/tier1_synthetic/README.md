# Tier 1 — synthetic corpus

Engraved scores with encoded ground truth. The image is synthetic (typeset, not
scanned) and the ground truth is exact and free, which makes this tier cheap to
scale but **optimistic** relative to real scans — keep its numbers separate from
Tier 2 in any report.

> **Status.** The only Tier-1 source so far is **GrandStaff**: engraved excerpts
> whose images come straight from the source dataset at its native (low, ~70 DPI)
> resolution, with `**kern` ground truth converted to MusicXML at fetch time. The
> rendering-from-public-domain-MusicXML pipeline and the image degradations
> sketched below are the intended design, **not yet implemented**.

Layout per sample:

```
<id>/
  image.{jpg,png}      # the engraved score image
  reference.musicxml   # ground truth
  meta.yaml            # provenance + license + tier
```

A GrandStaff sample's `meta.yaml` today:

```yaml
tier: tier1_synthetic
source: grandstaff
type: engraved
origin: <path within the source dataset>
license: <dataset terms>
```

Planned (once images are rendered from source MusicXML): a `render_engine` field
and a `degradations` list (e.g. `[blur, perspective_warp, jpeg_q40]`) recording
how each image was produced and degraded.
