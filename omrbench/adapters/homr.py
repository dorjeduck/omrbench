"""homr adapter (https://github.com/liebharc/homr).

homr writes ``<name>.musicxml`` next to its input image. We run it on a copy of
the input in a temp dir, then move the result to the expected output path.

The homr command is configurable so this works whether homr is on PATH or run
through Poetry/uvx:

    OMRBENCH_HOMR_CMD="homr"                         (default; pip/uvx install)
    OMRBENCH_HOMR_CMD="poetry run homr"              (Poetry checkout)
    OMRBENCH_HOMR_CWD="/path/to/homr"                (needed for `poetry run`)
"""

from __future__ import annotations

import os
import shlex
import shutil
import tempfile
from pathlib import Path

from omrbench.adapters.base import Adapter, move_into, run_subprocess
from omrbench.corpus import Sample


class HomrAdapter(Adapter):
    name = "homr"

    def __init__(self) -> None:
        self.cmd = shlex.split(os.environ.get("OMRBENCH_HOMR_CMD", "homr"))
        cwd = os.environ.get("OMRBENCH_HOMR_CWD")
        self.cwd = Path(cwd) if cwd else None

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
