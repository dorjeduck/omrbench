"""homr adapter (https://github.com/liebharc/homr).

homr writes ``<name>.musicxml`` next to its input image. We run it on a copy of
the input in a temp dir, then move the result to the expected output path.

The command (``cmd``) and working directory (``cwd``) come from the engine's
``omrbench.toml`` entry, so this works whether homr is on PATH or run through
Poetry/uvx:

    [engines.homr]                # pip/uvx install on PATH
    adapter = "homr"
    cmd     = "homr"

    [engines.homr-0_6]            # a specific checkout
    adapter = "homr"
    cmd     = "poetry run homr"
    cwd     = "/path/to/homr-v0.6"   # required when cmd must run from a dir
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from omrbench.adapters.base import Adapter, capture_subprocess, move_into, run_subprocess
from omrbench.corpus import Sample


class HomrAdapter(Adapter):
    def version(self) -> str | None:
        # homr exposes no --version flag; for a local checkout the git
        # description is the precise identifier. None for a PATH/uvx install.
        if self.cwd is None:
            return None
        return capture_subprocess(["git", "describe", "--tags", "--always"], cwd=self.cwd)

    def predict(self, sample: Sample, out_path: Path) -> bool:
        image = sample.image
        if image is None:
            return False
        with tempfile.TemporaryDirectory(prefix="omrbench-homr-") as tmp:
            tmp_dir = Path(tmp)
            work_image = tmp_dir / image.name
            shutil.copy(image, work_image)
            ok = run_subprocess([*self.cmd, str(work_image)], cwd=self.cwd)
            produced = work_image.with_suffix(".musicxml")
            if not ok or not produced.exists() or produced.stat().st_size == 0:
                return False
            move_into(produced, out_path)
        return True
