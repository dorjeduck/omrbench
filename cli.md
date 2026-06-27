# omrbench CLI

All commands are subcommands of `omrbench`.

## fetch

```
omrbench fetch <polish-scores|grandstaff> [--dest DIR]
                                          [--limit N] [--seed S] [--source-dir DIR]
```

Downloads a corpus into `corpora/` (override with `--dest`). `--limit`, `--seed`,
and `--source-dir` apply to `grandstaff` only: `--limit`/`--seed` select a
reproducible subset (defaults 200 / 0); `--source-dir` reuses an already-extracted
dataset instead of downloading.

Needs the `fetch` extra.

## run

```
omrbench run --engine NAME [--version V] --corpus DIR
```

Runs an engine declared in `omrbench.toml` over a corpus, writing
`runs/<engine>-<version>-<timestamp>/`. `--version` is required only when the
engine has more than one entry. Auto-scores the `music21` metric on completion.

## score

```
omrbench score [RUN_ID] [--metric NAME]
```

Scores a run, caching `runs/<run-id>/scores/<metric>.json`. Engine and corpus come
from the run, so only the id is needed. With a `RUN_ID`, prints a report and
re-scores. With no id, scores every run still missing that metric. `--metric`
defaults to `music21` (`omr-ned` needs the `omr-ned` extra).

## rm

```
omrbench rm RUN_ID [RUN_ID ...] [-f]
```

Deletes runs (predictions and scores included). Prompts per run unless `-f`.

## augment

```
omrbench augment --corpus DIR --out DIR
                 [--blur R] [--rotate DEG] [--noise N] [--jpeg Q] [--seed S]
```

Writes a degraded copy of a corpus (references unchanged). At least one
degradation is required: `--blur` (gaussian radius), `--rotate` (max degrees ±),
`--noise` (pixel noise 0–255), `--jpeg` (quality 1–95). `--seed` defaults to 0.

Needs the `augment` extra.

## serve

```
omrbench serve [--host HOST] [--port PORT]
```

Runs the local web UI (default `127.0.0.1:8000`). Needs the `serve` extra. See
`serve.md`.
