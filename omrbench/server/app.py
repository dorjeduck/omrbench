"""FastAPI app exposing the read layer over HTTP.

Every route is a thin call into `omrbench.records` / `omrbench.corpus` /
`omrbench.score` — no benchmark logic lives here. The static frontend is served
from `static/`.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
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

    @app.get("/api/runs/{run_id}/comparable")
    def comparable(run_id: str) -> list[dict]:
        try:
            return [asdict(r) for r in records.comparable_runs(run_id)]
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/scores/{metric}")
    def score(run_id: str, metric: str) -> dict:
        # Computed and cached on first request (on-demand scoring) — engine-free.
        try:
            return records.ensure_score(run_id, metric)
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

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


_SIDES = {"reference": "reference", "prediction": "prediction", "image": "image"}


def _resolve(run_id: str, sample_id: str, side: str) -> Path:
    """The on-disk file for one case+side, guarded against path traversal."""
    paths = records.case_paths(run_id, sample_id)
    path = getattr(paths, _SIDES[side])
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    resolved = path.resolve()
    if Path.cwd() not in resolved.parents:
        raise HTTPException(status_code=403, detail="forbidden")
    return resolved


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
