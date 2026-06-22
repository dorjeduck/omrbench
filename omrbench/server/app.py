"""FastAPI app exposing the read layer over HTTP.

Every route is a thin call into `omrbench.records` / `omrbench.corpus` /
`omrbench.score` — no benchmark logic lives here. The static frontend is served
from `static/`.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from omrbench import records
from omrbench.score import REGISTRY
from omrbench.server.metrics_doc import DESCRIPTIONS

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="omrbench")

    @app.get("/api/engines")
    def engines() -> list[str]:
        return records.list_engines()

    @app.get("/api/runs")
    def runs() -> list[dict]:
        return [asdict(r) for r in records.list_runs()]

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> dict:
        try:
            return records.load_run(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str) -> dict:
        from omrbench import runs as runs_mod

        try:
            runs_mod.delete_run(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.get("/api/runs/{run_id}/comparable")
    def comparable(run_id: str) -> list[dict]:
        try:
            return [asdict(r) for r in records.comparable_runs(run_id)]
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/scores/{metric}")
    def score(run_id: str, metric: str) -> dict:
        # Returns the cached score (computing it inline if missing). Cheap metrics
        # only — the UI uses the async start/progress pair below for heavy ones.
        try:
            return records.ensure_score(run_id, metric)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown metric: {metric}") from exc

    @app.post("/api/runs/{run_id}/scores/{metric}/start")
    def score_start(run_id: str, metric: str) -> dict:
        # Kick off scoring in the background; the client polls /progress. Engine-free.
        from omrbench.server import jobs
        try:
            return jobs.start(run_id, metric)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown metric: {metric}") from exc

    @app.get("/api/runs/{run_id}/scores/{metric}/progress")
    def score_progress(run_id: str, metric: str) -> dict:
        from omrbench.server import jobs
        try:
            return jobs.status(run_id, metric)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown metric: {metric}") from exc

    @app.post("/api/runs/{run_id}/scores/{metric}/cancel")
    def score_cancel(run_id: str, metric: str) -> dict:
        from omrbench.server import jobs
        try:
            return jobs.cancel(run_id, metric)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown metric: {metric}") from exc

    @app.get("/api/metrics")
    def metrics() -> list[dict]:
        # From the registry keys only — no metric is instantiated, so optional
        # heavy deps (e.g. musicdiff for omr-ned) are never imported here.
        return [
            {"name": name, **DESCRIPTIONS.get(name, {})} for name in sorted(REGISTRY)
        ]

    @app.get("/api/file/musicxml")
    def musicxml(
        run_id: str = Query(...),
        sample_id: str = Query(...),
        side: str = Query(..., pattern="^(reference|prediction)$"),
    ) -> FileResponse:
        path = _resolve(run_id, sample_id, side)
        return FileResponse(path, media_type="application/xml")

    @app.get("/api/file/image")
    def image(
        run_id: str = Query(...),
        sample_id: str = Query(...),
    ) -> FileResponse:
        return FileResponse(_resolve(run_id, sample_id, "image"))

    @app.post("/api/open")
    def open_file(
        run_id: str = Query(...),
        sample_id: str = Query(...),
        side: str = Query(..., pattern="^(reference|prediction|image)$"),
    ) -> dict:
        # The server is local, so it opens the file in the OS default app (the
        # user's MusicXML viewer / image viewer).
        _open_in_default_app(_resolve(run_id, sample_id, side))
        return {"ok": True}

    # --- corpora (read-write) ----------------------------------------------
    # Unlike the run routes above, these mutate the corpora/ tree (create dirs,
    # write/delete files). They call omrbench.corpus directly — engine-free —
    # the same way delete_run calls omrbench.runs. A corpus is identified by its
    # path (e.g. "corpora/polish_scores"), passed as a query param so
    # its slashes don't fight the router.

    @app.get("/api/corpora")
    def corpora() -> list[dict]:
        return [asdict(c) for c in records.list_corpora()]

    @app.get("/api/corpora/detail")
    def corpus_detail(corpus_id: str = Query(...)) -> dict:
        try:
            return records.corpus_detail(corpus_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/corpora")
    def create_corpus(name: str = Form(...)) -> dict:
        from omrbench import corpus

        try:
            path = corpus.create_corpus(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"path": str(path)}

    @app.delete("/api/corpora")
    def delete_corpus(corpus_id: str = Query(...)) -> dict:
        from omrbench import corpus

        try:
            corpus.delete_corpus(Path(corpus_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/corpora/samples/upload")
    def upload_sample(
        corpus_id: str = Query(...),
        image: UploadFile = File(...),
        reference: str = Form(...),
        source: str = Form(""),
        type: str = Form(""),
        license: str = Form(""),
        kind: str = Form(""),
    ) -> dict:
        from omrbench import corpus

        suffix = Path(image.filename or "").suffix or ".png"
        # kind is an optional informational tag, stored in meta when given.
        meta = {k: v for k, v in (("source", source), ("type", type), ("license", license), ("kind", kind)) if v}
        try:
            sample = corpus.add_sample(
                Path(corpus_id),
                image_bytes=image.file.read(),
                image_suffix=suffix,
                reference_xml=reference,
                meta=meta,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": sample.id}

    @app.post("/api/corpora/samples/curate")
    def curate_sample(
        corpus_id: str = Query(...),
        from_corpus: str = Form(...),
        from_sample_id: str = Form(...),
    ) -> dict:
        from omrbench import corpus
        from omrbench.corpus import Sample

        # Curation is free-form: any sample can be collected into any corpus
        # (e.g. a "hardest cases" set spanning sources). kind is informational and
        # rides along in the copied meta; nothing is blocked here.
        src = Sample(id=from_sample_id, dir=Path(from_corpus) / from_sample_id)
        try:
            sample = corpus.copy_sample(Path(corpus_id), src)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"id": sample.id}

    @app.delete("/api/corpora/samples")
    def delete_sample(corpus_id: str = Query(...), sample_id: str = Query(...)) -> dict:
        from omrbench import corpus

        try:
            corpus.remove_sample(Path(corpus_id), sample_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.get("/api/corpora/file/image")
    def corpus_image(corpus_id: str = Query(...), sample_id: str = Query(...)) -> FileResponse:
        return FileResponse(_safe(records.corpus_sample_paths(corpus_id, sample_id).image))

    @app.get("/api/corpora/file/musicxml")
    def corpus_musicxml(corpus_id: str = Query(...), sample_id: str = Query(...)) -> FileResponse:
        path = _safe(records.corpus_sample_paths(corpus_id, sample_id).reference)
        return FileResponse(path, media_type="application/xml")

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


_SIDES = {"reference": "reference", "prediction": "prediction", "image": "image"}


def _safe(path: Path | None) -> Path:
    """A file that exists and lives under cwd, or an HTTP error. The one guard
    against path traversal for every file the server hands out."""
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    resolved = path.resolve()
    if Path.cwd() not in resolved.parents:
        raise HTTPException(status_code=403, detail="forbidden")
    return resolved


def _resolve(run_id: str, sample_id: str, side: str) -> Path:
    """The on-disk file for one case+side, guarded against path traversal."""
    paths = records.case_paths(run_id, sample_id)
    return _safe(getattr(paths, _SIDES[side]))


def _open_in_default_app(path: Path) -> None:
    import os
    import subprocess
    import sys

    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # win only
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port)
