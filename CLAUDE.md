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
and `cli.py` work on MusicXML/`**kern` files alone. Engines plug in only through
`adapters/`, and adapters **shell out** (subprocess) — they do not import the
engine either. This is what keeps results comparable and lets someone install
omrbench with zero OMR tools present. If a change makes the core import an
engine, it is wrong.

```
corpus.py    sample discovery (id/ -> image + reference.musicxml + meta.yaml)
adapters/    "images -> MusicXML" subprocess wrappers, one file per engine
score/       MusicXML-vs-MusicXML metric; imports no engine
cli.py       omrbench fetch | run | score
```

## Corpus discipline

- **Two tiers, never mixed in a report.** `corpus/tier1_synthetic/` (rendered
  from known-good MusicXML — exact, free, *optimistic*) and `corpus/tier2_real/`
  (real scans, hand-verified — predictive, precious). Reporting them together
  hides the optimism in synthetic numbers.
- **Eval-only data stays eval-only.** The Tier-2 seed `btrkeks/polish-scores` is
  *evaluation only — never training*. That restriction is propagated into every
  sample's `meta.yaml` and stated in `LICENSE`. Do not weaken it.
- Downloaded/large corpus data is git-ignored (see `.gitignore`); fetch locally,
  do not commit the data.

## Metrics

- `music21` (default): note/key normalized edit distance, MusicXML-vs-MusicXML.
  No engine vocabulary, no `**kern` step. SER = distance / reference length.
- `omr-ned` (opt-in, currently a stub): OMR-literature metric on `**kern`. Only
  the engine *output* needs MusicXML->kern conversion — the known-fragile step,
  deliberately kept behind the flag, not in the default path.

## Commands

```bash
pip install -e .            # core
pip install -e '.[fetch]'   # + dataset download (datasets, huggingface_hub)

omrbench fetch polish-scores
omrbench run   --adapter homr --corpus corpus/tier2_real/polish_scores
omrbench score --pred predictions/homr --corpus corpus/tier2_real/polish_scores
```

`run` caches: a non-empty output file is not re-run; delete it to force a re-run.

## Testing the homr adapter against the local checkout

homr lives in a *separate* repo at `/Users/dorjeduck/dev/2026/pdf_mxml/homr`
(its own Poetry project; see that repo's CLAUDE.md for install/CoreML notes).
The adapter reads its command from the environment so omrbench never imports or
hard-codes homr:

```bash
export OMRBENCH_HOMR_CMD="poetry run homr"
export OMRBENCH_HOMR_CWD="/Users/dorjeduck/dev/2026/pdf_mxml/homr"
```

Default `OMRBENCH_HOMR_CMD` is just `homr` (pip/uvx install on PATH).

## Adding an engine

Implement `Adapter.predict(sample, out_path) -> bool` in
`omrbench/adapters/<engine>.py` (shell out; return False on failure, don't
raise) and register it in `omrbench/adapters/__init__.py`. Mirror
`adapters/homr.py`.

## Conventions

- Code license is **MIT** (corpus data carries its own licenses — see READMEs).
- Python >= 3.10; keep the core dependency set small (music21, editdistance,
  pyyaml). Heavy/optional deps go in the `fetch` extra.
- Skeleton stage — prefer small, verifiable additions over speculative
  framework. Match the existing module style.
