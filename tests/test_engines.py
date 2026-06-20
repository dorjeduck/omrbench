"""Tests for engine resolution: identity, default adapter, declared version."""

from __future__ import annotations

import pytest

from omrbench.adapters.homr import HomrAdapter
from omrbench.engines import load_engine


def _toml(tmp_path, body):
    path = tmp_path / "omrbench.toml"
    path.write_text(body)
    return path


def test_engine_is_identity_adapter_defaults_to_it(tmp_path):
    cfg = _toml(tmp_path, '[engines.homr-0_6_1]\nengine = "homr"\nversion = "0.6.1"\ncmd = "homr"\n')
    eng = load_engine("homr-0_6_1", config=cfg)
    assert eng.engine == "homr"            # tool identity (grouped on)
    assert eng.name == "homr-0_6_1"        # entry name (config key)
    assert isinstance(eng, HomrAdapter)    # adapter defaulted to engine "homr"
    assert eng.declared_version == "0.6.1"
    assert eng.resolved_version() == "0.6.1"  # declared wins, no auto-detect


def test_adapter_can_be_overridden(tmp_path):
    cfg = _toml(tmp_path, '[engines.x]\nengine = "mytool"\nadapter = "homr"\ncmd = "foo"\n')
    eng = load_engine("x", config=cfg)
    assert eng.engine == "mytool"
    assert isinstance(eng, HomrAdapter)    # driver differs from the tool name


def test_missing_engine_field_raises(tmp_path):
    cfg = _toml(tmp_path, '[engines.x]\ncmd = "foo"\n')
    with pytest.raises(KeyError):
        load_engine("x", config=cfg)


def test_unknown_adapter_raises(tmp_path):
    cfg = _toml(tmp_path, '[engines.x]\nengine = "nope"\ncmd = "foo"\n')
    with pytest.raises(KeyError):
        load_engine("x", config=cfg)
