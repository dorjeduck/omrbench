# Tier 1 — synthetic corpus

Engraved scores with encoded ground truth. The image is synthetic (typeset, not
scanned) and the ground truth is exact and free, which makes this tier cheap to
scale but **optimistic** relative to real scans — keep its numbers separate from
Tier 2 in any report.

> **Status.** The only Tier-1 source so far is **GrandStaff**: engraved excerpts
> whose images come straight from the source dataset at its native (low, ~70 DPI)
> resolution, with `**kern` ground truth converted to MusicXML at fetch time.
> Image degradations are implemented (`omrbench augment` — writes a degraded
> sibling corpus and records the degradations in `meta.yaml`); the
> rendering-from-public-domain-MusicXML pipeline (and a `render_engine` field) is
> the intended design, **not yet implemented**.

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

A corpus produced by `omrbench augment` additionally carries a `degradations`
list (e.g. `[blur=1.2, jpeg_q45]`), `augmented_from`, and `augment_seed`. Still
planned (once images are rendered from source MusicXML): a `render_engine` field
recording how each image was produced.
