# omrbench

A **tool-independent ground-truth benchmark for Optical Music Recognition (OMR)**.

Point it at any engine that emits MusicXML, get a comparable score against a
shared ground-truth corpus. The benchmark core imports **no** OMR engine —
engines plug in through thin subprocess adapters — so you can install and run
the corpus + scorer with zero OMR tools present, and add one engine at a time.

> Status: early skeleton. The homr adapter and the music21 metric run
> end-to-end; the corpus is seeded and grown over time.

## Why

Existing OMR benchmarks couple everything together: a gated dataset, every
engine installed at once, and a fragile cross-format conversion in the scoring
path. One broken piece blocks the whole thing. omrbench decouples the three
parts so each runs alone:

```
corpus/   images + reference MusicXML (+ optional **kern)   — the asset
adapters/ "images -> MusicXML" subprocess wrappers, 1 per engine
score/    MusicXML-vs-MusicXML, imports no engine            — the neutral judge
```

## Corpus tiers (reported separately, never mixed)

- **Tier 1 — synthetic**: rendered from known-good public-domain MusicXML.
  Ground truth is exact and free; degradations can be layered on. Scales cheaply
  but is optimistic vs real-world scans.
- **Tier 2 — real scans**: hand-verified transcriptions of real documents.
  Predictive of actual quality, small and precious. Seeded from
  [`btrkeks/polish-scores`](https://huggingface.co/datasets/btrkeks/polish-scores)
  (112 historical scans, dual MusicXML/**kern ground truth, **evaluation-only**).

Mixing the two hides the optimism in synthetic numbers, so reports keep them apart.

## Install

```bash
pip install -e .            # core: corpus + scorer + adapters
pip install -e '.[fetch]'   # + dataset download (datasets, huggingface_hub)
```

## Use

```bash
# 1. get a Tier-2 corpus
omrbench fetch polish-scores            # -> corpus/tier2_real/polish_scores/

# 2. run an engine (homr must be installed; see adapter docstring for config)
omrbench run --adapter homr --corpus corpus/tier2_real/polish_scores

# 3. score the predictions against the ground truth
omrbench score --pred predictions/homr --corpus corpus/tier2_real/polish_scores
```

`run` caches: a sample with a non-empty output is not re-run. Delete the output
file to force a re-run.

## Metrics

- **`music21`** (default): note/symbol-level normalized edit distance, computed
  MusicXML-vs-MusicXML. No engine vocabulary, no `**kern` step. SER = edit
  distance / reference length (0.0 = perfect).
- **`omr-ned`** (optional, *not yet implemented*): the OMR-literature metric on
  Humdrum `**kern`. The reference ships `**kern`, so only the engine output
  needs conversion — the one fragile step, kept behind an opt-in flag.

## Adding an engine

Implement `Adapter.predict(sample, out_path) -> bool` in
`omrbench/adapters/<engine>.py` (shell out; do not import the engine) and
register it in `omrbench/adapters/__init__.py`. See `adapters/homr.py`.

## License

Code: MIT. Corpus data carries its **own** licenses — see `corpus/*/README.md`
and per-sample `meta.yaml`. polish-scores is **evaluation-only; do not train**.
