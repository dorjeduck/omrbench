"""Tests for engine resolution: engine+version identity, default adapter."""

from __future__ import annotations

import pytest

from omrbench.adapters.homr import HomrAdapter
from omrbench.engines import (
    add_config_entry,
    available_adapters,
    delete_config_entry,
    list_config_entries,
    load_engine,
    update_config_entry,
)

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


# --- config editing (web UI CRUD) ------------------------------------------


def test_available_adapters_lists_registry_keys():
    assert "homr" in available_adapters()


def test_add_entry_roundtrips_through_load_engine(tmp_path):
    cfg = _toml(tmp_path, "")
    add_config_entry({"engine": "homr", "version": "0.7", "cmd": "homr"}, config=cfg)
    assert list_config_entries(cfg) == [{"engine": "homr", "version": "0.7", "cmd": "homr"}]
    eng = load_engine("homr", "0.7", config=cfg)
    assert isinstance(eng, HomrAdapter)
    assert eng.resolved_version() == "0.7"


def test_add_drops_blank_optionals(tmp_path):
    cfg = _toml(tmp_path, "")
    add_config_entry(
        {"engine": "homr", "version": "0.7", "cmd": "homr", "cwd": "", "adapter": ""}, config=cfg
    )
    assert "cwd" not in list_config_entries(cfg)[0]
    assert "adapter" not in list_config_entries(cfg)[0]


def test_no_timeout_by_default(tmp_path):
    cfg = _toml(tmp_path, '[[engines]]\nengine = "homr"\nversion = "0.7"\ncmd = "homr"\n')
    assert load_engine("homr", config=cfg).timeout is None


def test_timeout_roundtrips_as_number(tmp_path):
    cfg = _toml(tmp_path, "")
    add_config_entry({"engine": "homr", "version": "0.7", "cmd": "homr", "timeout": "120"}, config=cfg)
    # Stored as a TOML number, not a string, and surfaced on the adapter.
    assert list_config_entries(cfg)[0]["timeout"] == 120
    assert load_engine("homr", "0.7", config=cfg).timeout == 120.0


def test_blank_timeout_dropped(tmp_path):
    cfg = _toml(tmp_path, "")
    add_config_entry({"engine": "homr", "version": "0.7", "cmd": "homr", "timeout": ""}, config=cfg)
    assert "timeout" not in list_config_entries(cfg)[0]


def test_non_positive_timeout_raises(tmp_path):
    cfg = _toml(tmp_path, "")
    with pytest.raises(ValueError, match="positive number"):
        add_config_entry({"engine": "homr", "version": "0.7", "cmd": "homr", "timeout": "0"}, config=cfg)


def test_non_numeric_timeout_raises(tmp_path):
    cfg = _toml(tmp_path, "")
    with pytest.raises(ValueError, match="must be a number"):
        add_config_entry({"engine": "homr", "version": "0.7", "cmd": "homr", "timeout": "soon"}, config=cfg)


def test_add_duplicate_raises(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    with pytest.raises(KeyError, match="already exists"):
        add_config_entry({"engine": "homr", "version": "0.6.1", "cmd": "homr"}, config=cfg)


def test_add_missing_cmd_raises(tmp_path):
    cfg = _toml(tmp_path, "")
    with pytest.raises(ValueError, match="missing required 'cmd'"):
        add_config_entry({"engine": "homr", "version": "0.7"}, config=cfg)


def test_add_unknown_adapter_raises(tmp_path):
    cfg = _toml(tmp_path, "")
    with pytest.raises(ValueError, match="unknown adapter 'nope'"):
        add_config_entry(
            {"engine": "homr", "version": "0.7", "cmd": "homr", "adapter": "nope"}, config=cfg
        )


def test_update_changes_fields_and_identity(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    update_config_entry(
        "homr", "0.6.1", {"engine": "homr", "version": "0.6.3", "cmd": "homr", "cwd": "/new"}, config=cfg
    )
    eng = load_engine("homr", "0.6.3", config=cfg)
    assert eng.cwd.as_posix() == "/new"
    with pytest.raises(KeyError, match="declared versions"):
        load_engine("homr", "0.6.1", config=cfg)


def test_update_collision_raises(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    with pytest.raises(KeyError, match="already exists"):
        update_config_entry(
            "homr", "0.6.1", {"engine": "homr", "version": "0.6.2", "cmd": "homr"}, config=cfg
        )


def test_update_missing_raises(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    with pytest.raises(KeyError, match="no entry homr@9.9"):
        update_config_entry("homr", "9.9", {"engine": "homr", "version": "9.9", "cmd": "x"}, config=cfg)


def test_delete_removes_entry(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    delete_config_entry("homr", "0.6.1", config=cfg)
    versions = {str(e["version"]) for e in list_config_entries(cfg)}
    assert versions == {"0.6.2"}


def test_delete_missing_raises(tmp_path):
    cfg = _toml(tmp_path, TWO_HOMR)
    with pytest.raises(KeyError, match="no entry homr@9.9"):
        delete_config_entry("homr", "9.9", config=cfg)


def test_edit_preserves_comments(tmp_path):
    cfg = _toml(tmp_path, '# my engines\n[[engines]]\nengine = "homr"  # the tool\nversion = "0.6.2"\ncmd = "homr"\n')
    add_config_entry({"engine": "audiveris", "version": "5.3", "cmd": "audiveris"}, config=cfg)
    text = cfg.read_text()
    assert "# my engines" in text
    assert "# the tool" in text
    assert "audiveris" in text
