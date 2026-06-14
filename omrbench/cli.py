"""omrbench command line.

    omrbench fetch polish-scores [--dest DIR]
    omrbench run   --adapter homr --corpus DIR [--out DIR]
    omrbench score --pred DIR --corpus DIR [--metric music21]
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
    print(f"unknown dataset: {args.dataset}", file=sys.stderr)
    return 2


def _cmd_run(args: argparse.Namespace) -> int:
    from omrbench.adapters import get_adapter
    from omrbench.corpus import discover

    adapter = get_adapter(args.adapter)
    samples = discover(Path(args.corpus))
    out_dir = Path(args.out) if args.out else Path("predictions") / args.adapter
    results = adapter.run_corpus(samples, out_dir)
    ok = sum(1 for v in results.values() if v)
    # Capture the engine version now, while the engine is present, so `score`
    # (which imports no engine) can read it back from disk later.
    (out_dir / "run.json").write_text(
        json.dumps(
            {
                "engine": adapter.name,
                "engine_version": adapter.version(),
                "corpus": str(args.corpus),
                "date": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )
    print(f"{adapter.name}: {ok}/{len(results)} samples produced -> {out_dir}")
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    from omrbench.corpus import discover
    from omrbench.score import get_metric
    from omrbench.score.report import Report

    metric = get_metric(args.metric)
    samples = discover(Path(args.corpus))
    pred_dir = Path(args.pred)
    report = Report(metric=metric.name, corpus=str(args.corpus))
    for sample in samples:
        reference = (
            sample.reference_kern
            if getattr(metric, "requires_reference", "musicxml") == "kern"
            else sample.reference_musicxml
        )
        if not reference.exists():
            continue
        prediction = pred_dir / f"{sample.id}.musicxml"
        report.samples.append(metric.score(prediction, reference, sample.id))
    print(report.render())

    engine, engine_version = _read_run_meta(pred_dir)
    date = datetime.now(timezone.utc)
    record = report.to_record(engine, engine_version, _tier_of(args.corpus), date.isoformat())
    results_dir = Path("results") / engine
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"{date.strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(record, indent=2))
    print(f"\nwrote result record -> {out}")
    return 0


def _read_run_meta(pred_dir: Path) -> tuple[str, str | None]:
    """Engine name + version from the predictions' run.json, falling back to the
    prediction dir name when predictions were produced outside `omrbench run`."""
    meta_path = pred_dir / "run.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        return meta.get("engine", pred_dir.name), meta.get("engine_version")
    return pred_dir.name, None


def _tier_of(corpus: str) -> str | None:
    for part in Path(corpus).parts:
        if part.startswith("tier"):
            return part
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="omrbench")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="download a ground-truth corpus")
    p_fetch.add_argument("dataset", choices=["polish-scores"])
    p_fetch.add_argument("--dest", help="destination corpus dir")
    p_fetch.set_defaults(func=_cmd_fetch)

    p_run = sub.add_parser("run", help="run an OMR engine over a corpus")
    p_run.add_argument("--adapter", required=True)
    p_run.add_argument("--corpus", required=True)
    p_run.add_argument("--out")
    p_run.set_defaults(func=_cmd_run)

    p_score = sub.add_parser("score", help="score predictions against a corpus")
    p_score.add_argument("--pred", required=True)
    p_score.add_argument("--corpus", required=True)
    p_score.add_argument("--metric", default="music21")
    p_score.set_defaults(func=_cmd_score)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
