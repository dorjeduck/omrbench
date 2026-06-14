# omrbench

> ⚠️ **Early alpha.** APIs, corpus layout, and metrics may change without
> notice. Not yet ready for production use — expect rough edges.

A **tool-independent ground-truth benchmark for Optical Music Recognition (OMR)**.

Point it at any engine that emits MusicXML, get a comparable score against a
shared ground-truth corpus. The benchmark core imports **no** OMR engine —
engines plug in through thin subprocess adapters — so you can install and run
the corpus + scorer with zero OMR tools present, and add one engine at a time.

> Status: early skeleton. The homr adapter and the music21 metric run
> end-to-end; the corpus is seeded and expanded over time.

## Why

omrbench keeps its three components — the dataset, the engines, and the
scorer — independent, so each can run without the others. You can install the
corpus and scorer with no OMR tool present, add engines one at a time behind
subprocess adapters, and keep the scoring path free of any engine-specific or
cross-format conversion. Each component can be run and tested independently:

```
corpus/   images + reference MusicXML (+ optional **kern)
adapters/ "images -> MusicXML" subprocess wrappers, 1 per engine
score/    MusicXML-vs-MusicXML, imports no engine
```

## Corpus tiers (reported separately, never mixed)

- **Tier 1 — synthetic**: rendered from known-good public-domain MusicXML.
  Ground truth is exact and free, and degradations can be added. Cheap to scale
  but optimistic vs real-world scans.
- **Tier 2 — real scans**: hand-verified transcriptions of real documents.
  Predictive of actual quality, but limited in size. Seeded from
  [`btrkeks/polish-scores`](https://huggingface.co/datasets/btrkeks/polish-scores)
  (112 historical scans, dual MusicXML/**kern ground truth, **evaluation-only**).

Mixing the two would mask the optimism in the synthetic numbers, so reports keep
them separate.

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
  needs conversion — the fragile step, kept behind an opt-in flag.

> **On the metric.** SER here is a normalized Levenshtein edit distance over a
> reference symbol sequence — the same construction as Word/Character Error Rate
> in speech recognition and OCR. The construction is standard; the name "Symbol
> Error Rate" and the specific implementation (music21 token stream,
> MusicXML-vs-MusicXML) are this project's own. `omr-ned` is intended to follow
> the separate OMR-NED metric.

## Adding an engine

Implement `Adapter.predict(sample, out_path) -> bool` in
`omrbench/adapters/<engine>.py` (shell out; do not import the engine) and
register it in `omrbench/adapters/__init__.py`. See `adapters/homr.py`.

## License

Code: MIT. Corpus data carries its **own** licenses — see `corpus/*/README.md`
and per-sample `meta.yaml`. polish-scores is **evaluation-only; do not train**.
