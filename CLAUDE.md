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
engines.py   omrbench.toml read + edit; resolves engine+version -> an adapter
score/       MusicXML-vs-MusicXML metric; imports no engine
scoring.py   score a run's predictions against its corpus (engine-free); CLI + server share it
augment.py   synthetic-corpus image degradation for robustness probing (engine-free)
proc.py      run work under a wall-clock budget, killably (engine-free): the
             command runner adapters shell out through + the killable Job the
             server/CLI run Python workers in. One tree-kill, one place.
records.py   engine-free read layer over runs/ (used by the server)
server/      thin engine-free read/write HTTP layer + the static web UI
cli.py       omrbench fetch | run | score | augment | serve
```

A **run** is the unit (see `DESIGN.md`): `run` produces
`runs/<engine>-<version>-<timestamp>/`
with the predictions and a `run.json` recording engine + corpus; scoring is
engine-free and cached under `runs/<run-id>/scores/<metric>.json`, so `score`
needs only a run id. (`predictions/` and `results/` are the retired old layout.)

## Corpus discipline

- **`kind` is an informational per-sample tag, not a constraint.** Two values
  matter in practice: `synthetic` (image rendered from known-good MusicXML —
  exact, free, *optimistic*) and `real` (scans, hand-verified — predictive,
  precious). It lives in a sample's `meta.yaml`, or is inferred from a
  `synthetic/`/`real/` folder in its path when absent. Nothing is enforced on
  it — corpora can hold a mix, and you can collect across kinds freely (e.g. a
  "hardest cases" set). It's there for display and optional filtering. Just be
  aware when reading scores: averaging synthetic and real into one headline
  number hides the optimism in the synthetic part — that's a reporting judgement
  call, not something the tool blocks.
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
omrbench run   --engine homr --version 0.6.1 --corpus corpora/polish_scores  # -> a run id
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

## Timeouts (wall-clock budgets)

Both budgets are opt-in (omit ⇒ no limit) and enforced by the one toolkit in
`proc.py` (process-group tree-kill): nothing reaches for `subprocess.run(timeout=)`
or its own watchdog. They differ in *granularity* because the work differs:

- **Engine runs — per-sample.** An `[[engines]]` entry may set `timeout`
  (seconds). A sample whose engine runs longer has its whole process tree killed
  (via `proc.run_command`) and counts as *failed*, so one stuck image (e.g.
  homr's CoreML stalling on an odd input size) can't freeze a run. Per-sample is
  natural here because each sample is a fresh shelled-out command.

- **Scoring — whole-job.** A separate `[scoring]` table sets `timeout` (seconds).
  Scoring is engine-free *in-process* Python (no shelled-out command), and an
  in-process C call (a music21 parse) can't be interrupted per-sample — the only
  reliable stop is killing the worker process. So scoring runs in a killable
  child (`proc.Job`) with a whole-job cap, applied the **same** way to the server
  (`omrbench serve`) and the CLI (`omrbench score`) — both go through
  `proc.run_blocking` / `proc.Job`.

```toml
[[engines]]
engine  = "homr"
version = "0.6.2"
cmd     = "poetry run homr"
timeout = 180          # kill any one image that runs longer than 3 min

[scoring]
timeout = 600          # kill a scoring job that runs longer than 10 min
```

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

## Frontend rules

The web UI is **vanilla JS, no framework, no build step**: one `app.js` of
hash-routed `view*()` functions building DOM through the `el()` helper, one
`style.css`, heavy libs (OpenSheetMusicDisplay, Chart.js) from CDN only. The server
(`server/app.py`) stays the thin engine-free read/write layer — routes are calls
into `records`/`corpus`/`engines`, never benchmark logic. Keep it this way; do
not introduce a framework, bundler, or npm step for a skeleton-stage tool.

These rules exist because UI bugs here are usually **deducible from the code, not
the pixels** — if a layout is wrong it's wrong by construction, so reason about
it before claiming it's done.

- **Layout is CSS's job; never fake it with per-element sizing.** Width and
  alignment come from a CSS rule (a grid track, `width`, `flex`), not from
  `size=` / hand-guessed pixel counts on inputs. If you find yourself setting
  `size` to make things line up, the container is wrong.
- **A form is a two-column grid, not a stack of inline rows.** Label column +
  control column; every control shares one left edge and one width. `.filters`
  (inline flex) is for a *one-line* filter/action bar only — never a multi-field
  form. Stacking `.filters` rows is what staircases. Use the form grid primitive
  (build one if absent — don't re-roll raw layout per form).
- **Reuse the vocabulary before authoring layout.** Compose existing classes
  (`.card`, `.filters`, `.action`, `.del`, `.panel`, `.summary-list`, the form
  grid) and helpers (`el`, `getJSON`). If you're hand-rolling the same layout a
  third time, factor a primitive instead of repeating raw `el()` trees.
- **Build DOM with `el()`, not innerHTML, for any value from data.** `el()`
  text-nodes its children, which escapes them; `{ html }` / `innerHTML` is only
  for trusted, code-authored markup.
- **Mutations re-render, they don't hand-patch.** On a successful POST/PUT/
  DELETE, re-call the view function (re-fetch from the API) — the pattern every
  existing admin view uses. On failure, `alert()` the backend's `detail`
  (`(await r.json().catch(() => ({}))).detail || r.statusText`), never a bare
  status.
- **Label for the user, name keys for the machine.** Visible labels are plain
  words ("command to run", not the TOML key `cmd`); the raw key names live in the
  request body and the on-disk file, not the UI chrome. Don't repeat a field's
  label inside its own placeholder — the placeholder is an example or nothing.
- **Verify the rendered page before saying it's done.** At minimum re-read the
  built DOM for the column/alignment rules above; for visual changes, render and
  look. Do not report a UI change complete on the strength of "the code runs".

## Conventions

- Code license is **MIT** (corpus data carries its own licenses — see READMEs).
- Python >= 3.11; keep the core dependency set small (music21, editdistance,
  pyyaml). Heavy/optional deps go in their own extra (`fetch`, `omr-ned`).
- Skeleton stage — prefer small, verifiable additions over speculative
  framework. Match the existing module style.
