# omrbench — Technical Overview

A tool-independent benchmark that scores any OMR engine against a shared
ground-truth corpus. The core depends on no engine.

## Core concepts

**Engine** — an external OMR program omrbench drives as a subprocess to convert a
score image into MusicXML. Identified by `engine` + `version`; two installs of one
tool are two comparable entries.

**Corpus** — a set of samples, each pairing an input image with its ground-truth
MusicXML and some provenance. 

**Metric** — compares predicted MusicXML against the reference and yields a score
where lower is better. It works on MusicXML alone, so a score is comparable across
tools. Metrics are pluggable; the default is a normalized edit distance.

An **engine** turns a **corpus**'s images into predictions; a **metric** scores
them against the references.

## The four subpackages of `omrbench/`

**`adapters/`** — the engine boundary: the only code that interacts with an OMR engine.

**`fetch/`** — corpus ingestion: downloaders that normalize external datasets into
the corpus layout. 

**`score/`** — the metric engine: MusicXML-vs-MusicXML, engine-free, metrics
pluggable behind one contract.

**`server/`** — an HTTP layer and web UI over the same engine-free logic the CLI
uses.

## adapters/

### base.py

Defines the single interface every engine wrapper implements. It specifies the one
operation the benchmark needs from any engine — run on a sample image, produce a
MusicXML file, report success or failure — plus a shared driver that applies it
across a corpus (with caching and a per-sample time budget). Concrete engines
implement only `predict()` — how to invoke that specific engine.

Two adapters exist today:

- **`homr.py`** — homr (https://github.com/liebharc/homr).
- **`audiveris.py`** — Audiveris (https://github.com/Audiveris/audiveris).

## fetch/

Each fetcher downloads one external dataset and writes it out as an omrbench
corpus — sample dirs with `image`, `reference.musicxml`, and `meta.yaml`. Any
format conversion the source needs happens here, once, on the ground truth, so
nothing downstream sees the source's native format. Each fetcher also writes the
sample's `kind` and license into `meta.yaml`. Requires the optional `[fetch]`
extra.

Two fetchers included:

- **`polish_scores.py`** — `btrkeks/polish-scores`: 112 real historical scans
  (`kind: real`), eval-only license.
- **`grandstaff.py`** — GrandStaff: engraved pianoform excerpts (`kind:
  synthetic`); converts the source's `**kern` ground truth to MusicXML at fetch
  time.

## score/

### base.py

Defines the metric interface: score one prediction against one reference, then
aggregate the per-sample results into summary numbers. 

Two metrics implementation included:

- **`music21_metric.py`** — the default; per-part edit distance over MusicXML,
  score is SER (edit distance / reference length).
- **`omr_ned.py`** — optional (`[omr-ned]` extra); delegates to musicdiff's
  OMR-NED.

### report.py

Aggregates per-sample results into the report and the cached JSON score record.

## server/

A local web frontend. `app.py` is a FastAPI app exposing HTTP routes over the
read/write layer — list runs and corpora, view scores, edit engine config — and
serving the static, no-build UI. Engine runs and scoring are slow, so the server
launches them as background processes the browser polls (`runs_jobs.py`,
`jobs.py`). Like the CLI, it goes through the engine-free layer and contains no
benchmark logic itself.
