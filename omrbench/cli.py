"""omrbench command line.

    omrbench fetch polish-scores [--dest DIR]
    omrbench run   --engine ENGINE --corpus DIR [--metric music21]
    omrbench score --engine ENGINE --corpus DIR [--metric music21]

ENGINE names an entry in omrbench.toml; prediction and result paths are derived
from it (predictions/<engine>/, results/<engine>/).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _cmd_fetch(args: argparse.Namespace) -> int:
    if args.dataset == "polish-scores":
        from omrbench.fetch.polish_scores import fetch

        dest = Path(args.dest) if args.dest else Path("corpus/tier2_real/polish_scores")
        n = fetch(dest)
        print(f"wrote {n} samples to {dest}")
        return 0
    if args.dataset == "grandstaff":
        from omrbench.fetch.grandstaff import fetch

        dest = Path(args.dest) if args.dest else Path("corpus/tier1_synthetic/grandstaff")
        source_dir = Path(args.source_dir) if args.source_dir else None
        n = fetch(dest, limit=args.limit, seed=args.seed, source_dir=source_dir)
        print(f"wrote {n} samples to {dest}")
        return 0
    print(f"unknown dataset: {args.dataset}", file=sys.stderr)
    return 2


def _cmd_run(args: argparse.Namespace) -> int:
    from omrbench.corpus import discover
    from omrbench.engines import load_engine

    try:
        engine = load_engine(args.engine)
    except (FileNotFoundError, KeyError) as exc:
        print(str(exc).strip("'\""), file=sys.stderr)
        return 2
    samples = discover(Path(args.corpus))
    out_dir = Path("predictions") / args.engine
    results = engine.run_corpus(samples, out_dir)
    ok = sum(1 for v in results.values() if v)
    # Capture the engine version now, while the engine is present, so `score`
    # (which imports no engine) can read it back from disk later.
    (out_dir / "run.json").write_text(
        json.dumps(
            {
                "engine": args.engine,
                "engine_version": engine.version(),
                "corpus": str(args.corpus),
                "date": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )
    print(f"{args.engine}: {ok}/{len(results)} samples produced -> {out_dir}")
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    from omrbench.corpus import discover
    from omrbench.score import get_metric
    from omrbench.score.report import Report

    metric = get_metric(args.metric)
    samples = discover(Path(args.corpus))
    pred_dir = Path("predictions") / args.engine
    report = Report(metric=metric, corpus=str(args.corpus))
    for sample in samples:
        reference = sample.reference_musicxml
        if not reference.exists():
            continue
        prediction = pred_dir / f"{sample.id}.musicxml"
        report.samples.append(metric.score(prediction, reference, sample.id))
    print(report.render())

    engine_version = _read_run_version(pred_dir)
    date = datetime.now(timezone.utc)
    record = report.to_record(args.engine, engine_version, _tier_of(args.corpus), date.isoformat())
    results_dir = Path("results") / args.engine
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"{date.strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(record, indent=2))
    print(f"\nwrote result record -> {out}")
    return 0


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
    n = augment_corpus(Path(args.corpus), Path(args.out), degradations=degradations, seed=args.seed)
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


def _read_run_version(pred_dir: Path) -> str | None:
    """Engine version captured at `run` time, from the predictions' run.json.
    None when predictions were produced outside `omrbench run`."""
    meta_path = pred_dir / "run.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text()).get("engine_version")
    return None


def _tier_of(corpus: str) -> str | None:
    for part in Path(corpus).parts:
        if part.startswith("tier"):
            return part
    return None


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

    p_run = sub.add_parser("run", help="run an OMR engine over a corpus")
    p_run.add_argument("--engine", required=True, help="engine name from omrbench.toml")
    p_run.add_argument("--corpus", required=True)
    p_run.set_defaults(func=_cmd_run)

    p_score = sub.add_parser("score", help="score predictions against a corpus")
    p_score.add_argument("--engine", required=True, help="engine name (predictions/<engine>/)")
    p_score.add_argument("--corpus", required=True)
    p_score.add_argument("--metric", default="music21")
    p_score.set_defaults(func=_cmd_score)

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
