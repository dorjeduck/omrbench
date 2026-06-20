# Design: the **run** as the first-class unit

Status: proposal (not yet implemented). Reorients prediction storage, scoring,
and the reporting UI around "a run" instead of "an engine".

## Problem

Today predictions are keyed by **engine name** (`predictions/<engine>/`) and
scoring is a separate CLI step that re-states the engine *and* the corpus:

```
omrbench score --engine homr --corpus corpus/tier2_real/polish_scores
```

This is backwards:

- The engine and corpus are already fixed by the run that produced the
  predictions — re-stating them is redundant.
- One engine name == one predictions dir, so two homr runs, or homr on a
  *subset*, cannot coexist.
- Scoring is forced ahead-of-time even though it is cheap and engine-free.

## Core idea

A **run** is the first-class unit: `{ engine, corpus-or-subset, predictions,
metadata }`. Scoring, reporting, and comparison all derive from a run. You never
re-state engine or corpus — the run *is* them. Subsets and repeats are simply
different runs, separated by construction.

## On disk

Full repository layout. A run gets an id; predictions are stored per **run**, not
per engine, and `runs/` is the only new top-level dir — it absorbs both the old
`predictions/` and `results/`:

```
corpus/                                  # ground truth (unchanged)
  tier1_synthetic/grandstaff/<id>/{image.*, reference.musicxml, meta.yaml}
  tier2_real/polish_scores/<id>/{image.*, reference.musicxml, meta.yaml}

runs/                                    # NEW — replaces predictions/ and results/
  <run-id>/                              # e.g. homr-0.6.1-20260614T211232Z
    run.json                             # engine, version, command, corpus, date (+ samples only on a subset run)
    predictions/<id>.musicxml            # the engine output (precious, committed)
    scores/<metric>.json                 # cached score, written on demand by the server
```

`run.json`'s `samples` field is present **only on a subset run** (listing the
covered sample ids); a full-corpus run omits it, so absence means "whole corpus".

The old layout maps in cleanly:

- `predictions/<engine>/`        -> `runs/<run-id>/predictions/`
- `results/<engine>/<ts>.json`   -> `runs/<run-id>/scores/<metric>.json`
  (no longer hand-written by the CLI)

**run-id = `<engine>-<version>-<timestamp>`**, e.g. `homr-0.6.1-20260619T083012Z`.
Rationale:

- `engine` (the tool, e.g. `homr`) groups a tool's runs into one lineage;
- `version` distinguishes versions of the same tool *in the name itself* — the
  point of the engine/version model below;
- the timestamp makes it unique, chronologically sortable, and separates repeats;
- corpus stays out of the id — it is in `run.json` and shown as a list column, and
  corpus paths make ugly directory names.

Same-second collisions get a short suffix (`-b`). The version is sanitized for the
filename (e.g. a verbose `git describe` like `v0.6.2-54-g83074e1` is kept, just
made path-safe). Considered and rejected: pure timestamp (opaque on disk),
engine+corpus+timestamp (long, redundant with `run.json`), opaque hash.

## Engine identity, version, adapter

omrbench compares **engines** (tools, e.g. `homr`), and a tool evolves through
**versions** (`v0.6.1`, `v0.6.2`). Keeping these distinct is what enables the
lineage features (see the UI section): grouping a tool's runs, ordering them, and
framing a comparison as *regression* (same engine, two versions) vs *competition*
(two engines). So `run.json` records the **engine** (the tool — same string across
versions) and the **version** as separate fields.

A toml entry declares one runnable instance:

```toml
[engines.homr-0_6_1]       # entry name: a unique config key
engine  = "homr"           # required: the tool — the identity grouped on, and the
                           #   default adapter to load
version = "0.6.1"          # the version. Declared here; if omitted, fall back to
                           #   the adapter's auto-detect (e.g. git describe); if
                           #   neither yields one, `run` errors (can't name the run)
cmd     = "poetry run homr"
cwd     = "/path/to/homr-v0.6.1"
# adapter = "..."          # optional: the driver code (class in adapters/). Defaults
                           #   to `engine`; set only when the driver name differs
                           #   from the tool (e.g. a generic/shared adapter)
```

The user declares the **engine** (the tool they care about); **adapter** is
internal plumbing and only surfaces in config as an escape hatch. **version** is
crucial (it names and distinguishes the run), so it is required to end up known —
declared, else auto-detected.

## Scoring: on demand, cached

Scoring is engine-free and cheap (MusicXML-vs-MusicXML). So:

- The **server** computes a run's score the first time it is viewed under a
  metric, then caches it to `runs/<run-id>/scores/<metric>.json`.
- A fixed run + metric always yields the same score, so the cache key is
  `(run-id, metric)` — no timestamps, and predictions are immutable so the cache
  never needs invalidating.
- The engine-free rule holds: scoring never imports an engine.

## CLI

- `omrbench run …` produces a run (predictions + `run.json` under
  `runs/<run-id>/`).
- **No required `omrbench score`.** In the normal flow the web UI scores on
  demand; you never have to type a score command.
- **Optional `omrbench score` is kept** for headless use — it runs the same
  engine-free scoring the server does and writes `scores/<metric>.json`, for
  CI/regression checks (exit code or printed number), precomputing so the UI is
  instant, and scripting. Not needed when a browser is in the loop. It takes a
  **run-id** (engine and corpus come from the run's `run.json` — no `--engine`,
  no `--corpus`):

  ```
  omrbench score <run-id> [--metric music21]   # one run -> scores/<metric>.json
  omrbench score                               # every run missing that metric's score (CI/precompute)
  ```
- Producing and viewing a benchmark needs no argument gymnastics.

## Web UI (the reporting home — the terminal only *runs*)

Three views over runs:

1. **Runs list** (landing) — a row is a run; clicking it opens the run. Engine
   and corpus are **filters on top of the list**, not separate screens.
2. **Single-run detail** — worst cases, drill into a case (source image,
   prediction vs ground truth). Score computed/cached on open.
3. **Two-run head-to-head** — worst cases per side, plus the two delta sorts
   (where A beats B, where B beats A); a case shows both predictions against the
   one reference.

A **leaderboard** is the ranked summary over N runs sharing a corpus + metric.
Detailed per-case comparison is bounded to **exactly two** runs; N>2 is
leaderboard-only (to go deep on three engines, pick two).

**Trend** (one engine's score across repeated runs over time — "am I improving?")
is a *different* question from comparison (different engines at one moment). It is
inherently scoped to a single engine+corpus+metric, so it does not belong on the
landing (which should show what's there at a glance, not force a dropdown choice).
Drop it from the landing; keep the capability but surface it in an engine/run
context — e.g. reached from a run as "this engine's history on this corpus".

## Migration of existing data

Predictions are precious (real engine output, slow to regenerate, committed in
the repo); scores are derived (cheap, regenerable, and the one existing record is
on the pre-per-part-tokenizer basis, i.e. already stale). So:

- **Predictions -> migrate.** Move `predictions/homr/` into a run dir. Its
  `run.json` already has the engine and date, so the run-id falls out:
  `homr-20260614T211232Z`. Result: `runs/homr-20260614T211232Z/run.json` +
  `runs/homr-20260614T211232Z/predictions/0000.musicxml … 0111.musicxml`.
- **Result record -> drop.** `results/homr/20260614T211232Z.json` is a derived,
  stale cache; the new model re-scores from the migrated predictions on demand.
  `git rm` it — nothing is lost (predictions are the source of truth).
- **No `omrbench migrate` command.** One engine's data; a one-time manual
  `git mv` / `git rm` does it. Migration tooling for a single dataset is
  speculative — document the new layout, anyone else re-runs.

The actual move happens when the layout is implemented, not before.

## What this resolves

- No more `score --engine --corpus` — derived from the run.
- Subsets / repeated runs — separate runs by construction.
- Scoring is lazy and cached, not a mandatory CLI chore.

## Open questions

(none open — see the sections above for decided points.)
