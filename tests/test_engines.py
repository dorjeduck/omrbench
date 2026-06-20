"""Tests for engine resolution: engine+version identity, default adapter."""

from __future__ import annotations

import pytest

from omrbench.adapters.homr import HomrAdapter
from omrbench.engines import load_engine

TWO_HOMR = """
[[engines]]
engine = "homr"
version = "0.6.2"
cmd = "homr"

[[engines]]
engine = "homr"
version = "0.6.1"
cmd = "poetry run homr"
cwd = "/path/to/homr-v0.6.1"
"""


def _toml(tmp_path, body):
    path = tmp_path / "omrbench.toml"
    path.write_text(body)
    return path


def test_select_by_engine_and_version(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    eng = load_engine("homr", "0.6.1", config=cfg)
    assert eng.engine == "homr"                 # tool identity (grouped on)
    assert eng.resolved_version() == "0.6.1"
    assert eng.cwd.as_posix() == "/path/to/homr-v0.6.1"
    assert isinstance(eng, HomrAdapter)         # adapter defaulted to engine "homr"
    assert eng.name == "homr@0.6.1"             # entry identity = engine@version


def test_version_required_when_engine_has_several(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    with pytest.raises(KeyError, match="several versions"):
        load_engine("homr", config=cfg)


def test_version_optional_when_engine_has_one(tmp_path):
    cfg = _toml(tmp_path, '[[engines]]\nengine = "homr"\nversion = "0.7"\ncmd = "homr"\n')
    eng = load_engine("homr", config=cfg)
    assert eng.resolved_version() == "0.7"


def test_unknown_engine_raises(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    with pytest.raises(KeyError, match="unknown engine"):
        load_engine("nope", config=cfg)


def test_unknown_version_raises(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    with pytest.raises(KeyError, match="declared versions"):
        load_engine("homr", "9.9", config=cfg)


def test_adapter_override(tmp_path):
    cfg = _toml(tmp_path, '[[engines]]\nengine = "mytool"\nversion = "1"\nadapter = "homr"\ncmd = "foo"\n')
    eng = load_engine("mytool", config=cfg)
    assert eng.engine == "mytool"
    assert isinstance(eng, HomrAdapter)         # driver differs from the tool name


def test_missing_version_raises(tmp_path):
    cfg = _toml(tmp_path, '[[engines]]\nengine = "homr"\ncmd = "homr"\n')
    with pytest.raises(KeyError, match="unknown engine|missing required 'version'"):
        load_engine("homr", config=cfg)
