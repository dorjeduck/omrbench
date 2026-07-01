"""omrbench command line.

    omrbench fetch polish-scores [--dest DIR]
    omrbench run   --engine ENGINE --corpus DIR        -> a new run under runs/
    omrbench score [RUN_ID] [--metric music21]         -> runs/<run-id>/scores/<metric>.json
    omrbench rm    RUN_ID [RUN_ID ...] [-f]            -> delete run(s)
    omrbench augment --corpus DIR --out DIR ...        -> a degraded corpus copy
    omrbench serve [--host H] [--port P]               -> the local web UI

A *run* is the unit (see DESIGN.md): `run` produces
`runs/<engine>-<version>-<timestamp>/` holding the predictions and a `run.json`
that records the engine and corpus. So `score` only needs a run id — engine and
corpus come from the run; with no id it scores every run missing that metric's
score (precompute for CI / the web UI).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def _cmd_fetch(args: argparse.Namespace) -> int:
    if args.dataset == "polish-scores":
        from omrbench.fetch.polish_scores import fetch

        dest = Path(args.dest) if args.dest else Path("corpora/polish_scores")
        n = fetch(dest)
        print(f"wrote {n} samples to {dest}")
        return 0
    if args.dataset == "grandstaff":
        from omrbench.fetch.grandstaff import fetch

        dest = Path(args.dest) if args.dest else Path("corpora/grandstaff")
        source_dir = Path(args.source_dir) if args.source_dir else None
        n = fetch(dest, limit=args.limit, seed=args.seed, source_dir=source_dir)
        print(f"wrote {n} samples to {dest}")
        return 0
    print(f"unknown dataset: {args.dataset}", file=sys.stderr)
    return 2


def _cmd_run(args: argparse.Namespace) -> int:
    from omrbench import runs
    from omrbench.corpus import discover
    from omrbench.engines import load_engine

    try:
        engine = load_engine(args.engine, args.version)
    except (FileNotFoundError, KeyError) as exc:
        print(str(exc).strip("'\""), file=sys.stderr)
        return 2
    version = engine.resolved_version()
    if not version:
        # Mirrors the server's guard: the version is half a run's identity (it
        # names the run dir), so a run can't proceed without one.
        print(
            f"cannot determine a version for engine {args.engine!r}; declare 'version' in omrbench.toml",
            file=sys.stderr,
        )
        return 2
    samples = discover(Path(args.corpus))
    when = datetime.now(timezone.utc)
    run_dir = runs.create_run_dir(engine.engine, version, when)
    meta = runs.start_meta(
        engine.engine, version, " ".join(engine.cmd), str(args.corpus), when
    )
    runs.write_run_meta(run_dir, meta)
    results = engine.run_corpus(samples, run_dir / "predictions")
    final = runs.complete_meta(meta, results)
    runs.write_run_meta(run_dir, final)
    print(
        f"{run_dir.name}: {final['samples_produced']}/{len(results)} samples produced -> {run_dir}"
    )

    # Auto-score the cheap default metric so the run shows a number immediately
    # (the heavy omr-ned stays opt-in), under the same [scoring] budget `score`
    # uses. A scoring failure is not fatal: the run itself is complete on disk.
    from omrbench import scoring

    try:
        scoring.score_default(run_dir.name)
        print(f"{run_dir.name}: scored {scoring.DEFAULT_METRIC}")
    except (TimeoutError, RuntimeError) as exc:
        print(
            f"{run_dir.name}: auto-scoring failed ({exc}); "
            f"score it with `omrbench score {run_dir.name}`",
            file=sys.stderr,
        )
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    from omrbench import proc, runs, scoring
    from omrbench.score import get_metric
    from omrbench.score.report import Report

    try:
        metric = get_metric(args.metric)
    except KeyError as exc:
        print(str(exc).strip("'\""), file=sys.stderr)
        return 2
    except ImportError as exc:
        # An opt-in metric whose extra isn't installed; its factory's message
        # already says which extra to install.
        print(str(exc), file=sys.stderr)
        return 2
    if args.run:
        try:
            targets = [runs.load_run(args.run)]
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    else:
        targets = runs.list_runs()
        if not targets:
            print("no runs found under runs/", file=sys.stderr)
            return 2

    # Same wall-clock budget the server uses, so a hang can't burn unbounded time
    # here either; scoring runs in a killable child so the budget can be enforced.
    timeout = scoring.configured_timeout()

    def progress(run_id: str, done: int, total: int) -> None:
        end = "\n" if done == total else ""
        print(f"\rscoring {run_id} {done}/{total}", end=end, file=sys.stderr, flush=True)

    rc = 0
    for run in targets:
        # Zero-arg precompute skips runs already scored for this metric; an
        # explicit run id always re-scores.
        if not args.run and run.score_path(metric.name).exists():
            continue
        try:
            record = proc.run_blocking(
                scoring.score_to_cache, (run.run_id, args.metric), timeout=timeout,
                on_progress=lambda d, t, rid=run.run_id: progress(rid, d, t))
        except TimeoutError as exc:
            print(f"\n{run.run_id}: scoring {exc}", file=sys.stderr)
            rc = 1
            continue
        except RuntimeError as exc:
            print(f"\n{run.run_id}: scoring failed: {exc}", file=sys.stderr)
            rc = 1
            continue
        if args.run:
            print(Report.from_record(record, metric, run.corpus).render())
        print(f"{run.run_id}: {metric.name} -> {run.score_path(metric.name)}")
    return rc


def _cmd_rm(args: argparse.Namespace) -> int:
    from omrbench import runs

    code = 0
    for run_id in args.run:
        try:
            run = runs.load_run(run_id)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            code = 2
            continue
        if not args.force:
            preds = len(run.prediction_ids())
            scored = sorted(p.stem for p in run.scores_dir.glob("*.json")) if run.scores_dir.is_dir() else []
            scored_note = f", scored: {', '.join(scored)}" if scored else ""
            answer = input(f"delete run {run_id} ({preds} predictions{scored_note})? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print(f"skipped {run_id}")
                continue
        runs.delete_run(run_id)
        print(f"deleted {run_id}")
    return code


def _cmd_augment(args: argparse.Namespace) -> int:
    # Lazy import so the core install (without the `augment` extra) still works.
    try:
        from omrbench.augment import augment_corpus
    except ImportError:
        print(
            "augment needs the augment extra; install it with "
            "`pip install -e '.[augment]'`",
            file=sys.stderr,
        )
        return 2
    degradations = {
        "rotate": args.rotate,
        "blur": args.blur,
        "noise": args.noise,
        "jpeg": args.jpeg,
    }
    if all(v is None for v in degradations.values()):
        print(
            "specify at least one degradation (--blur/--rotate/--noise/--jpeg)",
            file=sys.stderr,
        )
        return 2
    try:
        n = augment_corpus(Path(args.corpus), Path(args.out), degradations=degradations, seed=args.seed)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"wrote {n} augmented samples to {args.out}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    # Lazy import so the core install (without the `serve` extra) still works.
    try:
        from omrbench.server.app import run_server
    except ImportError:
        print(
            "the web UI needs the serve extra; install it with "
            "`pip install -e '.[serve]'`",
            file=sys.stderr,
        )
        return 2
    print(f"omrbench serving on http://{args.host}:{args.port}")
    run_server(host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="omrbench")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="download a ground-truth corpus")
    p_fetch.add_argument("dataset", choices=["polish-scores", "grandstaff"])
    p_fetch.add_argument("--dest", help="destination corpus dir")
    p_fetch.add_argument("--limit", type=int, default=200, help="max samples (grandstaff)")
    p_fetch.add_argument("--seed", type=int, default=0, help="sampling seed (grandstaff)")
    p_fetch.add_argument(
        "--source-dir",
        help="grandstaff: existing extracted dataset dir to reuse "
        "(default datasets/grandstaff, downloaded if absent)",
    )
    p_fetch.set_defaults(func=_cmd_fetch)

    p_run = sub.add_parser("run", help="run an OMR engine over a corpus -> a new run")
    p_run.add_argument("--engine", required=True, help="engine (tool) name from omrbench.toml")
    p_run.add_argument("--version", help="engine version (needed when the engine has several)")
    p_run.add_argument("--corpus", required=True)
    p_run.set_defaults(func=_cmd_run)

    p_score = sub.add_parser("score", help="score a run (engine/corpus come from the run)")
    p_score.add_argument(
        "run", nargs="?", help="run id; omit to score every run missing this metric's score"
    )
    p_score.add_argument("--metric", default="music21")
    p_score.set_defaults(func=_cmd_score)

    p_rm = sub.add_parser("rm", help="delete one or more runs (id + predictions + scores)")
    p_rm.add_argument("run", nargs="+", help="run id(s) to delete")
    p_rm.add_argument("-f", "--force", action="store_true", help="delete without confirmation")
    p_rm.set_defaults(func=_cmd_rm)

    p_aug = sub.add_parser("augment", help="write a degraded copy of a corpus (needs .[augment])")
    p_aug.add_argument("--corpus", required=True, help="source corpus dir")
    p_aug.add_argument("--out", required=True, help="destination corpus dir (must differ)")
    p_aug.add_argument("--blur", type=float, help="gaussian blur radius")
    p_aug.add_argument("--rotate", type=float, help="max rotation magnitude in degrees (+/-)")
    p_aug.add_argument("--noise", type=float, help="uniform pixel-noise magnitude (0-255)")
    p_aug.add_argument("--jpeg", type=int, help="JPEG recompression quality (1-95)")
    p_aug.add_argument("--seed", type=int, default=0, help="augmentation seed (default 0)")
    p_aug.set_defaults(func=_cmd_augment)

    p_serve = sub.add_parser("serve", help="run the local web UI (needs .[serve])")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
