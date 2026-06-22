# real-scan corpus

Hand-verified transcriptions of **real** documents (scans/photos), with
authentic degradation. This is the kind that predicts real-world quality.

Layout per sample:

```
<id>/
  image.png            # the real scan
  reference.musicxml   # hand-verified ground truth
  reference.krn        # optional, **kern (enables the omr-ned metric)
  meta.yaml            # source, type, license
```

## polish-scores (seed source)

`omrbench fetch polish-scores` downloads
[`btrkeks/polish-scores`](https://huggingface.co/datasets/btrkeks/polish-scores)
into `polish_scores/` — 112 historical scans with dual MusicXML/**kern ground
truth, openly downloadable.

> **License: evaluation only — do NOT include this data in training sets.**
> Upstream: PRAIG / University of Alicante. This restriction propagates to every
> sample's `meta.yaml`. Respect it.

The downloaded `polish_scores/` folder is git-ignored — fetch it locally rather
than committing the data.
