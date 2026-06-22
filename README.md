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

## Corpus kinds (an informational tag)

Each sample can carry a `kind` (in its `meta.yaml`, or inferred from a
`synthetic/`/`real/` folder in its path). It's purely for display and optional
filtering — nothing is enforced, corpora may mix kinds, and you can collect
across them freely. The two values worth knowing:

- **synthetic**: engraved scores with encoded ground truth. Ground
  truth is exact and free. Cheap to scale but optimistic vs real-world scans —
  `omrbench augment` can degrade the images (blur/rotate/noise/JPEG) to probe how
  far that optimism holds.
- **real scans**: hand-verified transcriptions of real documents.
  Predictive of actual quality, but limited in size. Seeded from
  [`btrkeks/polish-scores`](https://huggingface.co/datasets/btrkeks/polish-scores)
  (112 historical scans, dual MusicXML/**kern ground truth, **evaluation-only**).

Just be aware when reading scores: averaging synthetic and real into one number
masks the optimism in the synthetic part, so it's usually worth reading them
separately.

## Install

```bash
pip install -e .            # core: corpus + scorer + adapters
pip install -e '.[fetch]'   # + dataset download (datasets, huggingface_hub)
pip install -e '.[omr-ned]' # + the omr-ned metric (musicdiff)
pip install -e '.[serve]'   # + local web UI (see serve.md)
pip install -e '.[augment]' # + corpus image degradation (omrbench augment)
```

## Use

```bash
# 1. get a corpus
omrbench fetch polish-scores               # real -> corpus/real/polish_scores/
omrbench fetch grandstaff --limit 200      # synthetic -> corpus/synthetic/grandstaff/

# 2. run an engine declared in omrbench.toml (see "Engines" below) -> a new run
omrbench run --engine homr --corpus corpus/real/polish_scores
#   prints the run id, e.g.  homr-20260614T210837Z

# 3. score that run (engine + corpus come from the run; no need to restate them)
omrbench score homr-20260614T210837Z
```

To probe robustness, write a degraded copy of a synthetic corpus and run against
it (reported separately — it stays the same kind as its source):

```bash
omrbench augment --corpus corpus/synthetic/grandstaff \
                 --out    corpus/synthetic/grandstaff_blur \
                 --blur 1.2 --rotate 2 --noise 12 --jpeg 45 --seed 1
```

Degradations are Pillow-only and reproducible (same `--seed` → byte-identical
images); references are copied unchanged and the applied degradations are
recorded in each sample's `meta.yaml`. It degrades, it does not upscale — it will
not make a low-DPI corpus easier for a resolution-sensitive engine.

A *run* is the unit: `run` writes everything under `runs/<run-id>/` (run-id is
`<engine>-<timestamp>`) — the predictions, a `run.json` recording the engine and
corpus, and any cached `scores/<metric>.json`. So `score` only needs the run id;
with no id it scores every run missing that metric's score. See **DESIGN.md**.

### Web UI

```bash
pip install -e '.[serve]'
omrbench serve              # -> http://127.0.0.1:8000
```

A lightweight, read-only local interface to browse runs and trends, inspect a
case's prediction side by side with the ground truth (rendered in-browser), and
read what each metric measures. See **[serve.md](serve.md)** for details.

### Engines

`omrbench.toml` is a list of `[[engines]]` entries, each a concrete install.
Copy `omrbench.toml.example` and edit. An entry is identified by **engine +
version** (no hand-typed label): `engine` is the tool (the identity runs group
on), `version` distinguishes installs; `adapter` (the driver code) defaults to
`engine`. So benchmarking two homr versions is two entries sharing
`engine = "homr"` with different `version`:

```toml
[[engines]]
engine  = "homr"
version = "0.7.0"
cmd     = "homr"

[[engines]]                   # same tool -> same lineage
engine  = "homr"
version = "0.6.0"
cmd     = "poetry run homr"
cwd     = "/path/to/homr-v0.6"
```

```bash
omrbench run   --engine homr --version 0.6.0 --corpus corpus/real/polish_scores
omrbench score <run-id>        # the run id that `run` printed
```

`--version` is needed only when an engine has more than one entry.

`grandstaff` is an engraved (synthetic) dataset of tens of thousands of
kern/image pairs (large download, cached); `--limit`/`--seed` select a
reproducible subset. Note it is the training data of some engines (e.g. homr),
so scores there are in-distribution and optimistic — choosing a source suited to
the engine under test is the user's call. Its images are small, low-resolution
engraved excerpts (~70 DPI); engines that expect full-page ~300 DPI scans
(e.g. Audiveris) may fail to transcribe them — a corpus/engine fit issue, not a
recognition result.

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

Two adapters ship: `homr` and `audiveris`. To add your own, implement
`Adapter.predict(sample, out_path) -> bool` in `omrbench/adapters/<engine>.py`
(shell out; do not import the engine) and register it in
`omrbench/adapters/__init__.py`. See `adapters/homr.py` for an engine that emits
`.musicxml` directly, or `adapters/audiveris.py` for one that exports compressed
`.mxl` and needs unpacking.

## License

Code: MIT. Corpus data carries its **own** licenses — see `corpus/*/README.md`
and per-sample `meta.yaml`. polish-scores is **evaluation-only; do not train**.
