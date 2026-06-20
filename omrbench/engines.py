"""Engine configs declared in ``omrbench.toml``.

The config is a list of entries, each one a concrete install of an engine. An
entry is identified by the pair **engine + version** (no hand-typed label): the
``engine`` is the tool (e.g. ``homr``, shared across versions, what runs group
on), and ``version`` distinguishes installs of it. So benchmarking two homr
versions is two entries that share ``engine = "homr"`` and differ in ``version``:

    [[engines]]
    engine  = "homr"
    version = "0.6.2"
    cmd     = "poetry run homr"
    cwd     = "/path/to/homr"

    [[engines]]
    engine  = "homr"
    version = "0.6.1"
    cmd     = "poetry run homr"
    cwd     = "/path/to/homr-v0.6.1"

``adapter`` (the driver code in ``adapters/``) is optional and defaults to
``engine``. The benchmark core still never imports an engine: this module only
reads strings from a config file and hands them to an adapter that shells out.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from omrbench.adapters import REGISTRY, Adapter

DEFAULT_CONFIG = Path("omrbench.toml")


def _entries(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"no engine config at {path}; declare engines as [[engines]] entries there"
        )
    return tomllib.loads(path.read_text()).get("engines", [])


def _ident(entry: dict) -> str:
    return f"{entry.get('engine', '?')}@{entry.get('version', '?')}"


def load_engine(engine: str, version: str | None = None, config: Path | None = None) -> Adapter:
    """Resolve an engine (and version) to a ready-to-run adapter, or raise with a
    clear message. An entry is identified by engine + version; ``version`` may be
    omitted only when the engine has exactly one entry."""
    path = config or DEFAULT_CONFIG
    entries = _entries(path)

    matches = [e for e in entries if e.get("engine") == engine]
    if not matches:
        known = ", ".join(sorted({_ident(e) for e in entries})) or "(none)"
        raise KeyError(f"unknown engine {engine!r}; declared: {known}")

    if version is None:
        if len(matches) > 1:
            versions = ", ".join(sorted(str(e.get("version")) for e in matches))
            raise KeyError(
                f"engine {engine!r} has several versions ({versions}); pass --version"
            )
        entry = matches[0]
    else:
        byver = [e for e in matches if str(e.get("version")) == version]
        if not byver:
            versions = ", ".join(sorted(str(e.get("version")) for e in matches))
            raise KeyError(
                f"no {engine!r} version {version!r}; declared versions: {versions}"
            )
        if len(byver) > 1:
            raise KeyError(f"duplicate config for {engine}@{version}")
        entry = byver[0]

    if not entry.get("version"):
        raise KeyError(f"engine entry {engine!r} is missing required 'version'")
    if "cmd" not in entry:
        raise KeyError(f"engine entry {_ident(entry)} is missing required 'cmd'")

    # The adapter (driver code) defaults to the tool name; override only when the
    # driver differs from the tool.
    adapter_type = entry.get("adapter", engine)
    if adapter_type not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(
            f"engine entry {_ident(entry)} uses unknown adapter {adapter_type!r}; "
            f"known adapters: {known}"
        )

    return REGISTRY[adapter_type](
        name=_ident(entry),
        cmd=entry["cmd"],
        cwd=entry.get("cwd"),
        engine=engine,
        declared_version=str(entry["version"]),
    )
