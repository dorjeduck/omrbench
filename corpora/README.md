# Corpus

A corpus is a directory of sample sub-directories, one level under `corpora/`:

```
corpora/<name>/
  <id>/
    image.{jpg,png}      # the OMR input
    reference.musicxml   # the ground truth (required for scoring)
    meta.yaml            # provenance + license (+ optional kind, source, type)
```

The layout is flat — the corpus name is its identifier (e.g. `polish_scores`,
`grandstaff`). Downloaded/large corpus data is git-ignored; fetch it locally,
don't commit it.

## `kind` — an informational tag, not a constraint

Each sample may carry a `kind` in its `meta.yaml`. Two values matter in practice:

- **synthetic** — the image is rendered from known-good MusicXML, so the ground
  truth is exact and free. Cheap to scale but **optimistic** relative to real
  scans. `omrbench augment` can degrade synthetic images (blur/rotate/noise/JPEG)
  to probe how far that optimism holds.
- **real** — a hand-verified transcription of an actual scan/photo. Predictive of
  real-world quality, but scarce.

Nothing is enforced on `kind`: a corpus may mix kinds, and you can collect across
them freely (e.g. a "hardest cases" set). It's there for display and optional
filtering. Just be aware when reading scores — averaging synthetic and real into
one headline number hides the optimism in the synthetic part, so it's usually
worth reading them separately. That's a reporting judgement call, not a tool rule.

## Seed sources

- **grandstaff** (`omrbench fetch grandstaff`) — synthetic. Engraved GrandStaff
  excerpts (Ríos-Vila et al.); `**kern` ground truth converted to MusicXML at
  fetch time. Images come at the source's native (low, ~70 DPI) resolution.
- **polish_scores** (`omrbench fetch polish-scores`) — real. 112 historical scans
  from [`btrkeks/polish-scores`](https://huggingface.co/datasets/btrkeks/polish-scores),
  dual MusicXML/`**kern` ground truth.

  > **License: evaluation only — do NOT include this data in training sets.**
  > Upstream: PRAIG / University of Alicante. This restriction propagates to
  > every sample's `meta.yaml`. Respect it.

A corpus produced by `omrbench augment` additionally carries a `degradations`
list (e.g. `[blur=1.2, jpeg_q45]`), `augmented_from`, and `augment_seed`.
