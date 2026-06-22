# CLAUDE.md

Guidance for Claude Code when working in **omrbench** — a tool-independent
ground-truth benchmark for Optical Music Recognition (OMR).

## What this project is

A benchmark that scores *any* OMR engine emitting MusicXML against a shared
ground-truth corpus. It is **not** an OMR tool and depends on no specific
engine. Eventual goal: a standalone GitHub repo that homr's maintainer (or
anyone) can adopt or run alongside their own project.

## The one rule that defines the architecture

**The benchmark core must never import an OMR engine.** `corpus.py`, `score/`,
and `cli.py` work on MusicXML files alone. Engines plug in only through
`adapters/`, and adapters **shell out** (subprocess) — they do not import the
engine either. This is what keeps results comparable and lets someone install
omrbench with zero OMR tools present. If a change makes the core import an
engine, it is wrong.

```
corpus.py    sample discovery (id/ -> image + reference.musicxml + meta.yaml)
runs.py      the run as the on-disk unit: runs/<run-id>/ (run.json, predictions/, scores/)
adapters/    "images -> MusicXML" subprocess wrappers, one file per engine
score/       MusicXML-vs-MusicXML metric; imports no engine
records.py   engine-free read layer over runs/ (used by the server)
cli.py       omrbench fetch | run | score | augment | serve
```

A **run** is the unit (see `DESIGN.md`): `run` produces `runs/<engine>-<timestamp>/`
with the predictions and a `run.json` recording engine + corpus; scoring is
engine-free and cached under `runs/<run-id>/scores/<metric>.json`, so `score`
needs only a run id. (`predictions/` and `results/` are the retired old layout.)

## Corpus discipline

- **Two kinds, never mixed in a report.** `corpus/synthetic/` (rendered
  from known-good MusicXML — exact, free, *optimistic*) and `corpus/real/`
  (real scans, hand-verified — predictive, precious). Reporting them together
  hides the optimism in synthetic numbers. A corpus's kind is its top folder
  (`synthetic`/`real`), derived from the path — not stored in `meta.yaml`.
- **Eval-only data stays eval-only.** The real seed `btrkeks/polish-scores` is
  *evaluation only — never training*. That restriction is propagated into every
  sample's `meta.yaml` and stated in `LICENSE`. Do not weaken it.
- Downloaded/large corpus data is git-ignored (see `.gitignore`); fetch locally,
  do not commit the data.

## Metrics

Metrics are pluggable via a **structural contract** (`score/base.py`): a metric
is any object with `name`, `primary`, `score()`, `aggregate()`, and an optional
`format()` — a `typing.Protocol`, **not** an ABC,
so a metric satisfies it by shape and need not import/subclass anything (a third
party could drop one in without importing omrbench). The core is metric-agnostic:

- A metric owns its own *result shape* — `SampleResult.fields` is an open dict of
  named per-sample numbers — and its own *aggregation* (`aggregate()` returns
  whatever summary keys it defines). The report and the JSON record just carry
  whatever the metric produces; `primary` names the one field (lower=better) used
  for ranking/medians.
- Display units live with the metric, not the report: the optional `format(key,
  value)` hook renders that metric's numbers (e.g. ratios as `%`, counts as
  ints); the report falls back to `base.default_format` if a metric omits it.

Metrics:

- `music21` (default): note/key normalized edit distance, MusicXML-vs-MusicXML.
  No engine vocabulary, no `**kern` step. SER = distance / reference length.
- `omr-ned` (opt-in, `.[omr-ned]` extra): **musicdiff's OMR-NED** — the metric is
  computed by `musicdiff` (Greg Chapman's MusicDiff, MIT; the implementation the
  Sheet Music Benchmark paper builds on) and we read its result:
  `(I + D) / (N1 + N2)`. It works on parsed MusicXML directly. Numbers are
  musicdiff's, not guaranteed paper-identical. musicdiff is heavy/slow, hence
  opt-in.

## Commands

```bash
pip install -e .            # core
pip install -e '.[fetch]'   # + dataset download (datasets, huggingface_hub)
pip install -e '.[omr-ned]' # + the omr-ned metric (musicdiff)

omrbench fetch polish-scores
omrbench run   --engine homr --version 0.6.1 --corpus corpus/real/polish_scores  # -> a run id
omrbench score <run-id>                       # engine + corpus come from run.json
omrbench score <run-id> --metric omr-ned
omrbench score                                # score every run missing that metric
```

`omrbench.toml` is a list of `[[engines]]` entries, each identified by **engine +
version** (no hand-typed label). `--engine` (+ `--version` when an engine has more
than one) on `run` selects one; the run lands in
`runs/<engine>-<version>-<timestamp>/`. Two versions of one tool are two entries
sharing `engine` → one lineage.

`run` caches: a non-empty prediction file is not re-run; delete it to force a
re-run.

## Testing the homr adapter against the local checkout

homr lives in a *separate* repo at `/Users/dorjeduck/dev/2026/pdf_mxml/homr`
(its own Poetry project; see that repo's CLAUDE.md for install/CoreML notes).
The command and working dir come from an `omrbench.toml` entry, so omrbench
never imports or hard-codes homr:

```toml
[[engines]]
engine  = "homr"        # the tool (identity + default adapter)
version = "0.6.2"       # names this install; with engine it identifies the entry
cmd     = "poetry run homr"
cwd     = "/Users/dorjeduck/dev/2026/pdf_mxml/homr"
```

Then `omrbench run --engine homr --version 0.6.2 ...`. A pip/uvx install on PATH
is just `cmd = "homr"` with no `cwd`.

## Adding an engine

Implement `Adapter.predict(sample, out_path) -> bool` in
`omrbench/adapters/<engine>.py` (shell out; return False on failure, don't
raise) and register it in `omrbench/adapters/__init__.py`. Mirror
`adapters/homr.py`.

## Adding a metric

Write a class satisfying `score/base.Metric` (see `score/music21_metric.py`) and
register it as a zero-arg factory in `score/__init__.py`'s `REGISTRY` — one line.
Factories, not classes, so a metric with heavy/optional deps imports them only
when selected (mirror how `omr-ned` lazy-imports `musicdiff`, and put such deps
in their own extra). No change to `report.py`/`cli.py` should be needed; if one
is, the contract is leaking and the change is suspect.

## Conventions

- Code license is **MIT** (corpus data carries its own licenses — see READMEs).
- Python >= 3.11; keep the core dependency set small (music21, editdistance,
  pyyaml). Heavy/optional deps go in their own extra (`fetch`, `omr-ned`).
- Skeleton stage — prefer small, verifiable additions over speculative
  framework. Match the existing module style.
