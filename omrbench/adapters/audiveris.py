"""Audiveris adapter (https://github.com/Audiveris/audiveris).

Audiveris is a Java application run here in batch mode. Unlike homr (which drops
a ``.musicxml`` next to its input), Audiveris exports a *compressed* ``.mxl``
into a per-book subfolder under its ``-output`` directory. This adapter points
Audiveris at a private temp output dir, finds the produced ``.mxl``, and extracts
the uncompressed MusicXML out of it to ``<sample_id>.musicxml`` — so the rest of
the pipeline sees the same plain MusicXML it gets from any other engine.

The command (``cmd``) and working directory (``cwd``) come from the engine's
``omrbench.toml`` entry (a ``[[engines]]`` array element, identified by
``engine`` + ``version``), so this works whether Audiveris is a launcher on PATH
or invoked through ``java -jar``:

    [[engines]]
    engine  = "audiveris"
    version = "5.10.2"
    cmd     = "audiveris"                 # the Audiveris launcher script on PATH

    [[engines]]
    engine  = "audiveris"
    version = "5.10-jar"
    cmd     = "java -jar /path/to/audiveris.jar"
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from omrbench.adapters.base import Adapter
from omrbench.corpus import Sample
from omrbench.proc import capture_command, run_command


def _parse_version(text: str | None) -> str | None:
    """Pull the version number out of Audiveris's multi-line ``-version`` block
    (``- Version:      5.10.2``). Falls back to the trimmed text if the expected
    line is absent, and to None if there is nothing."""
    if not text:
        return None
    for line in text.splitlines():
        if "Version:" in line:
            return line.split("Version:", 1)[1].strip() or None
    return text.strip() or None


def _find_mxl(export_dir: Path, stem: str) -> Path | None:
    """The .mxl Audiveris wrote under ``export_dir`` (it nests each book in its
    own subfolder). Prefer one named after the input; otherwise the first."""
    candidates = sorted(export_dir.rglob("*.mxl"))
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.stem == stem:
            return candidate
    return candidates[0]


def _mxl_to_musicxml(mxl_path: Path, out_path: Path) -> bool:
    """Extract the root MusicXML document from an ``.mxl`` (a ZIP whose root file
    is named in ``META-INF/container.xml``) and write it to ``out_path``. Returns
    False on any malformed-container error rather than raising."""
    try:
        with zipfile.ZipFile(mxl_path) as archive:
            container = archive.read("META-INF/container.xml")
            # namespace-agnostic: the container uses a default xmlns
            rootfile = ElementTree.fromstring(container).find(".//{*}rootfile")
            inner = rootfile.get("full-path") if rootfile is not None else None
            if not inner:
                return False
            data = archive.read(inner)
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return True


class AudiverisAdapter(Adapter):
    def version(self) -> str | None:
        # Best-effort: recent builds print a `-version` block (we keep just the
        # number); older ones don't support the flag, in which case
        # capture_command returns None. Never imports the engine.
        return _parse_version(capture_command([*self.cmd, "-version"], cwd=self.cwd))

    def predict(self, sample: Sample, out_path: Path) -> bool:
        image = sample.image
        if image is None:
            return False
        with tempfile.TemporaryDirectory(prefix="omrbench-audiveris-") as tmp:
            export_dir = Path(tmp) / "out"
            export_dir.mkdir()
            ok = run_command(
                [*self.cmd, "-batch", "-export", "-output", str(export_dir), "--", str(image)],
                cwd=self.cwd, timeout=self.timeout,
            )
            if not ok:
                return False
            produced = _find_mxl(export_dir, image.stem)
            if produced is None or produced.stat().st_size == 0:
                return False
            return _mxl_to_musicxml(produced, out_path)
