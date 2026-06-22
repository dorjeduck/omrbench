# omrbench web UI (`omrbench serve`)

A lightweight **local** web interface for browsing benchmark results, inspecting
individual cases against the ground truth, and reading what each metric measures.

It is **read-only**: it shows what `omrbench run` / `omrbench score` have already
produced under `runs/<run-id>/` (the predictions, `run.json`, and the cached
`scores/<metric>.json`). It runs no benchmark and imports no OMR engine — the same
discipline as the rest of omrbench. Notation is rendered in the browser by
[Verovio](https://www.verovio.org) (WebAssembly), so no extra Python dependency
is needed for it.

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
A table of every run under `runs/`: date, engine, version, corpus, kind, samples
scored, and the headline (size-weighted) SER. Click a row to open the run.

**Run detail**
The run's summary numbers, a **histogram** of the per-sample primary field
(e.g. SER binned 0–100 %+), and a **worst-samples** table. Click a worst-sample
row to inspect it.

**Case view** — compare a prediction with the ground truth
Three panels side by side: the **source scan**, the **ground-truth** notation,
and the **prediction** notation, plus that sample's metric numbers. The two
notations are rendered from MusicXML by Verovio, so you can *see* where the
engine diverged.

**Metrics** (top nav)
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

- **Read-only.** To get a new run on the dashboard, score from the CLI as usual
  (`omrbench score …`) and refresh the page.
- **Internet on first use.** Verovio and Chart.js load from a CDN; the browser
  caches them afterwards.
- **Reloading changes.** Frontend changes (`omrbench/server/static/`) appear on a
  browser refresh; changes to the Python server require restarting `omrbench
  serve`.
