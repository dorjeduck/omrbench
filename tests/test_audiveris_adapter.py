"""Tests for the Audiveris adapter's engine-free helpers: locating the produced
.mxl and extracting plain MusicXML out of it. The subprocess call to Audiveris
itself is not exercised (no engine present)."""

from __future__ import annotations

import zipfile

from omrbench.adapters.audiveris import _find_mxl, _mxl_to_musicxml, _parse_version

CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<container><rootfiles>'
    '<rootfile full-path="{inner}" media-type="application/vnd.recordare.musicxml+xml"/>'
    '</rootfiles></container>'
)


def _write_mxl(path, inner_name="score.xml", inner_xml="<score-partwise/>"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", CONTAINER.format(inner=inner_name))
        archive.writestr(inner_name, inner_xml)
    return path


# --- _parse_version --------------------------------------------------------


def test_parse_version_extracts_number_from_block():
    block = "Audiveris\n- Version:      5.10.2\n- Commit:       abc123\n- OS: Mac OS X\n"
    assert _parse_version(block) == "5.10.2"


def test_parse_version_none_when_empty():
    assert _parse_version(None) is None
    assert _parse_version("") is None


def test_parse_version_falls_back_to_trimmed_text():
    assert _parse_version("  weird-build-7  ") == "weird-build-7"


# --- _find_mxl -------------------------------------------------------------


def test_find_mxl_prefers_name_matching_input_stem(tmp_path):
    # Audiveris nests each book in its own subfolder under the output dir
    (tmp_path / "0000").mkdir()
    (tmp_path / "other").mkdir()
    match = _write_mxl(tmp_path / "0000" / "0000.mxl")
    _write_mxl(tmp_path / "other" / "other.mxl")
    assert _find_mxl(tmp_path, "0000") == match


def test_find_mxl_falls_back_to_first_when_no_stem_match(tmp_path):
    first = _write_mxl(tmp_path / "a.mxl")
    _write_mxl(tmp_path / "b.mxl")
    assert _find_mxl(tmp_path, "nomatch") == first  # sorted: 'a.mxl' first


def test_find_mxl_none_when_absent(tmp_path):
    assert _find_mxl(tmp_path, "0000") is None


# --- _mxl_to_musicxml ------------------------------------------------------


def test_mxl_extracts_root_document(tmp_path):
    mxl = _write_mxl(tmp_path / "in.mxl", inner_name="myscore.xml", inner_xml="<score-partwise>X</score-partwise>")
    out = tmp_path / "0000.musicxml"
    assert _mxl_to_musicxml(mxl, out) is True
    assert out.read_text() == "<score-partwise>X</score-partwise>"


def test_mxl_creates_parent_dir(tmp_path):
    mxl = _write_mxl(tmp_path / "in.mxl")
    out = tmp_path / "predictions" / "audiveris" / "0000.musicxml"
    assert _mxl_to_musicxml(mxl, out) is True
    assert out.is_file()


def test_mxl_bad_zip_returns_false(tmp_path):
    bad = tmp_path / "in.mxl"
    bad.write_text("not a zip")
    out = tmp_path / "0000.musicxml"
    assert _mxl_to_musicxml(bad, out) is False
    assert not out.exists()


def test_mxl_missing_rootfile_returns_false(tmp_path):
    mxl = tmp_path / "in.mxl"
    with zipfile.ZipFile(mxl, "w") as archive:
        archive.writestr("META-INF/container.xml", "<container><rootfiles/></container>")
    out = tmp_path / "0000.musicxml"
    assert _mxl_to_musicxml(mxl, out) is False
