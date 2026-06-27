# omrbench

omrbench is a ground-truth benchmark for Optical Music Recognition (OMR). It
scores any OMR engine — software that transcribes an image of a score into
MusicXML — against a shared corpus of score images paired with ground-truth
MusicXML.

> **Experimental.** Early stage, but end-to-end. Ships today: two engine
> adapters (homr, Audiveris), two metrics (music21 SER, opt-in omr-ned), a CLI,
> and a local web UI. The corpus is small and growing. Corpus layout, metrics,
> and APIs may still change.

## Install

```bash
pip install -e '.[all]'     # everything below
```

Or install only the extras you need:

```bash
pip install -e .            # core: corpus + scorer + adapters
pip install -e '.[fetch]'   # dataset download (datasets, huggingface_hub)
pip install -e '.[omr-ned]' # the omr-ned metric (musicdiff)
pip install -e '.[serve]'   # local web UI (see serve.md)
pip install -e '.[augment]' # corpus image degradation
```

## Use

`run` needs an engine declared in `omrbench.toml` (see [Add your
engine](#add-your-engine)).

```bash
omrbench fetch polish-scores                       # -> corpora/polish_scores/
omrbench run --engine homr --corpus corpora/polish_scores  # -> a run id
omrbench score homr-0.7.0-20260614T210837Z         # engine + corpus from run.json
```

Each `run` creates `runs/<engine>-<version>-<timestamp>/` with the predictions, a
`run.json` recording the engine and corpus, and — once scored —
`scores/<metric>.json`. `score` takes that run id and reads them back; with no id
it scores every run still missing the given metric.

`run` caches: a sample with non-empty output is not re-run. Delete the output to
force a re-run.

## Add your engine

An engine is declared in `omrbench.toml` as an `[[engines]]` entry, identified by
`engine` + `version`. Copy `omrbench.toml.example`. Two versions of one tool are
two entries sharing `engine`; `--version` is required only when an engine has
more than one entry.

```toml
[[engines]]
engine  = "homr"
version = "0.7.0"
cmd     = "homr"

[[engines]]
engine  = "homr"
version = "0.6.0"
cmd     = "poetry run homr"
cwd     = "/path/to/homr-v0.6"
```

If your engine is already on PATH and outputs MusicXML, the `homr` or `audiveris`
adapter may run it as-is. Otherwise, add an adapter: implement
`Adapter.predict(sample, out_path) -> bool` in `omrbench/adapters/<engine>.py`
(shell out, do not import the engine) and register it in
`omrbench/adapters/__init__.py`. See `adapters/homr.py` (writes `.musicxml`) or
`adapters/audiveris.py` (exports `.mxl`, needs unpacking), and
[tech_overview.md](tech_overview.md) for the adapter contract.

## Corpus

A corpus is a directory of samples — each a score image paired with its
ground-truth MusicXML.

omrbench has fetchers for two corpora so far:

- **polish-scores** (real) — hand-verified scans of historical documents: 112
  scans with dual MusicXML/`**kern` ground truth, evaluation-only. Predictive but
  scarce. From
  [`btrkeks/polish-scores`](https://huggingface.co/datasets/btrkeks/polish-scores).
- **grandstaff** (synthetic) — a large set of MusicXML rendered to images, so the
  ground truth is exact and cheap to scale, but scores run optimistic.
  `omrbench fetch grandstaff --limit N --seed S` takes a reproducible subset. It
  is training data for some engines (e.g. homr), so scores there are
  in-distribution. Its images are small ~70 DPI excerpts; engines expecting
  full-page ~300 DPI scans (e.g. Audiveris) may fail to transcribe them.

### augment

Synthetic images are clean; real scans carry blur, skew, noise, and compression
artifacts. `augment` writes a copy of a corpus with the images degraded and the
ground-truth MusicXML left untouched — a synthetic corpus made harder, closing
some of the gap to real-scan conditions.

```bash
omrbench augment --corpus corpora/grandstaff --out corpora/grandstaff_blur \
                 --blur 1.2 --rotate 2 --noise 12 --jpeg 45 --seed 1
```

Pillow-only and reproducible (same `--seed` -> identical images). References are
copied unchanged; applied degradations are recorded in each `meta.yaml`. It
degrades only — it will not upscale a low-DPI corpus.

## Metrics

- **`music21`** (default): note/symbol-level normalized edit distance,
  MusicXML-vs-MusicXML. SER = edit distance / reference length (0.0 = perfect).
  No `**kern` step.
- **`omr-ned`** (opt-in, `.[omr-ned]`): musicdiff's OMR-NED — a normalized edit
  distance between the two scores, computed by
  [musicdiff](https://github.com/gregchapman-dev/musicdiff) on parsed MusicXML.
  The implementation behind the
  [Sheet Music Benchmark paper](https://arxiv.org/abs/2506.10488); numbers are
  musicdiff's own, not guaranteed paper-identical. Compute-intensive, hence
  opt-in.

SER is a normalized Levenshtein distance over a reference symbol sequence (same
construction as WER/CER). The construction is standard; the name and the music21
token stream are this project's own. Both metrics work on MusicXML directly.

Add a metric: a class satisfying `score/base.Metric`, registered as a zero-arg
factory in `score/__init__.py`'s `REGISTRY`. See
[tech_overview.md](tech_overview.md) for the metric contract.

## Web UI

```bash
pip install -e '.[serve]'
omrbench serve              # -> http://127.0.0.1:8000
```

Browse runs, inspect a prediction beside its ground truth (rendered in-browser),
launch/stop runs, score on demand, edit `omrbench.toml`, and manage corpora. It
stays engine-free, shelling out exactly as the CLI does. See [serve.md](serve.md).

The same operations are available on the command line, for scripted workflows —
see [cli.md](cli.md).

## License

Code: MIT. Corpus data carries its own licenses — see [corpora/README.md](corpora/README.md) and
per-sample `meta.yaml`. polish-scores is evaluation-only; do not train.
