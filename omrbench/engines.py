"""Named engine instances declared in ``omrbench.toml``.

An engine instance binds an *adapter* (the code that drives an OMR engine) to a
concrete command and optional working directory. This is what ``--engine``
names, and it is the only place a homr install/version/location is recorded — so
benchmarking two homr versions is just two entries, with no environment
variables and no hand-set output paths.

    [engines.homr]                # pip/uvx install on PATH
    adapter = "homr"
    cmd     = "homr"

    [engines.homr-0_6]            # a specific checkout
    adapter = "homr"
    cmd     = "poetry run homr"
    cwd     = "/path/to/homr-v0.6"   # optional: required when cmd must run from
                                      # a specific dir (e.g. poetry run)

The benchmark core still never imports an engine: this module only reads strings
from a config file and hands them to an adapter that shells out.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from omrbench.adapters import REGISTRY, Adapter

DEFAULT_CONFIG = Path("omrbench.toml")


def load_engine(name: str, config: Path | None = None) -> Adapter:
    """Resolve engine ``name`` to a ready-to-run adapter, or raise with a clear
    message. Exactly one rule: the name must be an entry in ``omrbench.toml``."""
    path = config or DEFAULT_CONFIG
    if not path.exists():
        raise FileNotFoundError(
            f"no engine config at {path}; declare engines in [engines.<name>] there"
        )
    engines = tomllib.loads(path.read_text()).get("engines", {})
    if name not in engines:
        known = ", ".join(sorted(engines)) or "(none)"
        raise KeyError(f"unknown engine {name!r}; declared engines: {known}")

    entry = engines[name]
    adapter_type = entry.get("adapter")
    if adapter_type not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(
            f"engine {name!r} uses unknown adapter {adapter_type!r}; known adapters: {known}"
        )
    if "cmd" not in entry:
        raise KeyError(f"engine {name!r} is missing required 'cmd'")

    return REGISTRY[adapter_type](name=name, cmd=entry["cmd"], cwd=entry.get("cwd"))
