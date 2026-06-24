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

    timeout = entry.get("timeout")
    return REGISTRY[adapter_type](
        name=_ident(entry),
        cmd=entry["cmd"],
        cwd=entry.get("cwd"),
        engine=engine,
        declared_version=str(entry["version"]),
        timeout=float(timeout) if timeout is not None else None,
    )


# --- config editing (used by the web UI) -----------------------------------
# The CLI only ever *reads* the config (above, via stdlib tomllib). The local
# server lets the user edit omrbench.toml from the browser; those writes go
# through tomlkit so the file's comments/formatting survive an edit. This is
# still engine-free: it reads/writes strings and validates the adapter against
# REGISTRY keys — no engine is imported.

def available_adapters() -> list[str]:
    """Adapter *type* names a config entry may bind to (the REGISTRY keys)."""
    return sorted(REGISTRY)


def list_config_entries(config: Path | None = None) -> list[dict]:
    """The declared entries as plain dicts; ``[]`` when no config file exists."""
    path = config or DEFAULT_CONFIG
    if not path.exists():
        return []
    return tomllib.loads(path.read_text()).get("engines", [])


def _validate(entry: dict) -> dict:
    """Normalise and validate one entry, or raise ValueError. Returns a clean
    dict with blank optionals dropped; ``timeout`` is kept as a number."""
    clean: dict = {k: str(v).strip() for k, v in entry.items()
                   if k != "timeout" and str(v).strip()}
    for req in ("engine", "version", "cmd"):
        if not clean.get(req):
            raise ValueError(f"engine entry is missing required {req!r}")
    adapter = clean.get("adapter", clean["engine"])
    if adapter not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise ValueError(f"unknown adapter {adapter!r}; known adapters: {known}")
    raw = entry.get("timeout")
    if raw is not None and str(raw).strip():
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"timeout must be a number of seconds, got {raw!r}")
        if seconds <= 0:
            raise ValueError("timeout must be a positive number of seconds")
        clean["timeout"] = int(seconds) if seconds.is_integer() else seconds
    return clean


def _load_doc(path: Path):
    import tomlkit

    doc = tomlkit.parse(path.read_text()) if path.exists() else tomlkit.document()
    if "engines" not in doc:
        doc["engines"] = tomlkit.aot()
    return doc


def _find(aot, engine: str, version: str) -> int:
    for i, e in enumerate(aot):
        if e.get("engine") == engine and str(e.get("version")) == str(version):
            return i
    return -1


def _to_table(entry: dict):
    import tomlkit

    table = tomlkit.table()
    # Stable, readable key order; optionals only when present.
    for key in ("engine", "version", "cmd", "cwd", "adapter", "timeout"):
        if key in entry:
            table[key] = entry[key]
    return table


def add_config_entry(entry: dict, config: Path | None = None) -> None:
    """Append a new entry. Raises ValueError on bad input, KeyError on a
    duplicate engine+version."""
    import tomlkit

    path = config or DEFAULT_CONFIG
    clean = _validate(entry)
    doc = _load_doc(path)
    aot = doc["engines"]
    if _find(aot, clean["engine"], clean["version"]) != -1:
        raise KeyError(f"{clean['engine']}@{clean['version']} already exists")
    aot.append(_to_table(clean))
    path.write_text(tomlkit.dumps(doc))


def update_config_entry(
    old_engine: str, old_version: str, entry: dict, config: Path | None = None
) -> None:
    """Replace the entry identified by ``old_engine``+``old_version`` with
    ``entry``. Raises KeyError if the original is absent or the new identity
    collides with a different entry; ValueError on bad input."""
    import tomlkit

    path = config or DEFAULT_CONFIG
    clean = _validate(entry)
    doc = _load_doc(path)
    aot = doc["engines"]
    idx = _find(aot, old_engine, old_version)
    if idx == -1:
        raise KeyError(f"no entry {old_engine}@{old_version}")
    clash = _find(aot, clean["engine"], clean["version"])
    if clash != -1 and clash != idx:
        raise KeyError(f"{clean['engine']}@{clean['version']} already exists")
    aot[idx] = _to_table(clean)
    path.write_text(tomlkit.dumps(doc))


def delete_config_entry(engine: str, version: str, config: Path | None = None) -> None:
    """Remove the entry identified by engine+version, or raise KeyError."""
    import tomlkit

    path = config or DEFAULT_CONFIG
    doc = _load_doc(path)
    aot = doc["engines"]
    idx = _find(aot, engine, version)
    if idx == -1:
        raise KeyError(f"no entry {engine}@{version}")
    del aot[idx]
    path.write_text(tomlkit.dumps(doc))
