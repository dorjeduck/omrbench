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
pip install -e '.[omr-ned]' # + the omr-ned metric (musicdiff)
pip install -e '.[serve]'   # + local web UI (see serve.md)
```

## Use

```bash
# 1. get a corpus
omrbench fetch polish-scores               # Tier 2 -> corpus/tier2_real/polish_scores/
omrbench fetch grandstaff --limit 200      # Tier 1 -> corpus/tier1_synthetic/grandstaff/

# 2. run an engine declared in omrbench.toml (see "Engines" below)
omrbench run --engine homr --corpus corpus/tier2_real/polish_scores

# 3. score the predictions against the ground truth
omrbench score --engine homr --corpus corpus/tier2_real/polish_scores
```

Prediction and result paths are derived from the engine name
(`predictions/<engine>/`, `results/<engine>/`) — nothing to set by hand.

### Web UI

```bash
pip install -e '.[serve]'
omrbench serve              # -> http://127.0.0.1:8000
```

A lightweight, read-only local interface to browse runs and trends, inspect a
case's prediction side by side with the ground truth (rendered in-browser), and
read what each metric measures. See **[serve.md](serve.md)** for details.

### Engines

An engine is a named entry in `omrbench.toml` binding an adapter (the code that
drives an OMR tool) to a command and optional working directory. Copy
`omrbench.toml.example` to `omrbench.toml` and edit. This is the only place a
tool's install/version/location lives — so benchmarking two homr versions is
just two entries:

```toml
[engines.homr]                # pip/uvx install on PATH
adapter = "homr"
cmd     = "homr"

[engines.homr-0_6]            # a specific checkout
adapter = "homr"
cmd     = "poetry run homr"
cwd     = "/path/to/homr-v0.6"   # optional: required when cmd must run from a dir
```

```bash
omrbench run   --engine homr-0_6 --corpus corpus/tier2_real/polish_scores
omrbench score --engine homr-0_6 --corpus corpus/tier2_real/polish_scores
```

`grandstaff` is an engraved (synthetic) dataset of tens of thousands of
kern/image pairs (large download, cached); `--limit`/`--seed` select a
reproducible subset. Note it is the training data of some engines (e.g. homr),
so scores there are in-distribution and optimistic — choosing a source suited to
the engine under test is the user's call.

`run` caches: a sample with a non-empty output is not re-run. Delete the output
file to force a re-run.

## Metrics

- **`music21`** (default): note/symbol-level normalized edit distance, computed
  MusicXML-vs-MusicXML. No engine vocabulary, no `**kern` step. SER = edit
  distance / reference length (0.0 = perfect).
- **`omr-ned`** (optional, `.[omr-ned]` extra): **musicdiff's OMR-NED**, computed
  by [musicdiff](https://github.com/gregchapman-dev/musicdiff) (Greg Chapman's
  MusicDiff, MIT) directly on the parsed MusicXML — `(I + D) / (N1 + N2)`. It is
  the implementation the [Sheet Music Benchmark paper](https://arxiv.org/abs/2506.10488)
  builds on; the numbers are musicdiff's own, not guaranteed paper-identical.
  musicdiff is heavy and slow, hence opt-in.

> **On the metrics.** SER is a normalized Levenshtein edit distance over a
> reference symbol sequence — the same construction as Word/Character Error Rate
> in speech recognition and OCR. The construction is standard; the name "Symbol
> Error Rate" and the specific implementation (music21 token stream,
> MusicXML-vs-MusicXML) are this project's own. `omr-ned` instead defers entirely
> to musicdiff's published OMR-NED.

Both metrics work on MusicXML directly; neither uses a `**kern` step.

## Adding an engine

Implement `Adapter.predict(sample, out_path) -> bool` in
`omrbench/adapters/<engine>.py` (shell out; do not import the engine) and
register it in `omrbench/adapters/__init__.py`. See `adapters/homr.py`.

## License

Code: MIT. Corpus data carries its **own** licenses — see `corpus/*/README.md`
and per-sample `meta.yaml`. polish-scores is **evaluation-only; do not train**.
