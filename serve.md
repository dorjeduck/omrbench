# omrbench web UI (`omrbench serve`)

A lightweight **local** web interface for browsing benchmark results, inspecting
individual cases against the ground truth, and reading what each metric measures —
and for driving the benchmark itself: launching and stopping engine runs, scoring
on demand, editing engine config, and managing corpora.

It **imports no OMR engine** — the same discipline as the rest of omrbench. Where
it produces a run it shells out to the engine through the same adapter the CLI
uses; everything it reads and writes lives under `runs/<run-id>/` (the
predictions, `run.json`, and the cached `scores/<metric>.json`), `corpora/`, and
`omrbench.toml`. Notation is rendered in the browser by
[OpenSheetMusicDisplay](https://opensheetmusicdisplay.org) (loaded from a CDN), so
no extra Python dependency is needed for it.

## Install & run

```bash
pip install -e '.[serve]'     # adds fastapi + uvicorn
omrbench serve                # -> http://127.0.0.1:8000
```

Run it from the project root — the `runs/` directory is resolved relative to the
working directory. Options:

```bash
omrbench serve --port 8077 --host 0.0.0.0
```

Open the printed URL in a browser. Stop with `Ctrl-C`.

## What you can do

**Runs** (landing page)
One table per metric, each row a run: date, engine, version, corpus, and that
metric's headline (size-weighted) score. A broken/partial run is flagged. From
here you can **launch a new run** (pick an engine entry + corpus), watch
in-progress runs with a live progress bar and **stop** one (kept as a flagged,
resumable partial), filter by engine/corpus/metric, and delete a run. Click a row
to open it.

**Run detail**
The run's summary numbers, a **histogram** of the per-sample primary field
(e.g. SER binned 0–100 %+), and a **sortable samples** table (worst-first by
default). Metrics a run has not been scored on get a **Score** button that
computes them in the background (the slow `omr-ned` runs as a cancellable job).
Two runs on the same corpus can be put **head-to-head**. Click a sample row to
inspect it.

**Case view** — compare a prediction with the ground truth
Three panels side by side: the **source scan**, the **ground-truth** notation,
and the **prediction** notation, plus that sample's metric numbers. The two
notations are rendered from MusicXML by OpenSheetMusicDisplay, so you can *see*
where the engine diverged. From here you can also **copy the sample** into another
corpus (curation).

**Engines** (top nav)
Edit `omrbench.toml` from the browser: add, edit, or delete engine entries
(engine + version + command + working dir + adapter + per-image timeout). Writes
go through tomlkit so the file's comments and formatting survive.

**Corpora** (top nav)
Browse every corpus under `corpora/`, create a new one, upload an authored sample
(image + ground-truth MusicXML, validated on upload) or curate samples in from
another corpus, and delete samples or whole corpora.

**Docs** (top nav)
Plain-language explanation of each registered metric — what it computes and what
each per-sample field and aggregate means.

## Open in your own viewer

Each case panel has an **Open ↗** link that opens that file (the scan, the
reference MusicXML, or the prediction MusicXML) in your operating system's
default application — `open` on macOS, the default handler on Windows,
`xdg-open` on Linux. This is handy for the worst cases: an engine's broken output
sometimes can't be rendered inline (the notation panel shows *"notation
unavailable"*), but you can still open the file in your installed MusicXML viewer.

## Notes

- **Local tool, no auth.** The server reads and writes your `runs/`, `corpora/`,
  and `omrbench.toml`, and can launch engine subprocesses — bind it to localhost
  (the default `127.0.0.1`), not a shared network.
- **Internet on first use.** OpenSheetMusicDisplay and Chart.js load from a CDN;
  the browser caches them afterwards.
- **Reloading changes.** Frontend changes (`omrbench/server/static/`) appear on a
  browser refresh; changes to the Python server require restarting `omrbench
  serve`.
