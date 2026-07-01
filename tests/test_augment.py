"""Tests for the augment module: transforms are deterministic and degrading, and
augment_corpus writes a parallel corpus with copied references and recorded meta.
Engine-free; builds tiny images in tmp, no corpus download."""

from __future__ import annotations

import random

import pytest
import yaml
from PIL import Image

from omrbench.augment import augment_corpus, augment_image, degradation_tokens


def _checkerboard(size=64):
    img = Image.new("RGB", (size, size), "white")
    for y in range(size):
        for x in range(size):
            if (x // 8 + y // 8) % 2 == 0:
                img.putpixel((x, y), (0, 0, 0))
    return img


def _bytes(img):
    return img.convert("RGB").tobytes()


# --- transforms: deterministic + actually change the image -----------------


def test_blur_changes_image_and_is_deterministic():
    base = _checkerboard()
    a = augment_image(base, rng=random.Random("x"), blur=2.0)
    b = augment_image(base, rng=random.Random("x"), blur=2.0)
    assert _bytes(a) == _bytes(b)
    assert _bytes(a) != _bytes(base)


def test_noise_deterministic_for_same_seed_differs_across_seeds():
    base = _checkerboard()
    a = augment_image(base, rng=random.Random("seed-a"), noise=20.0)
    a2 = augment_image(base, rng=random.Random("seed-a"), noise=20.0)
    b = augment_image(base, rng=random.Random("seed-b"), noise=20.0)
    assert _bytes(a) == _bytes(a2)  # same seed -> identical
    assert _bytes(a) != _bytes(b)  # different seed -> different
    assert _bytes(a) != _bytes(base)


def test_rotate_grows_canvas_and_is_deterministic():
    base = _checkerboard()
    a = augment_image(base, rng=random.Random("r"), rotate=5.0)
    b = augment_image(base, rng=random.Random("r"), rotate=5.0)
    assert a.size == b.size
    assert a.size[0] >= base.size[0]  # expand=True never shrinks
    assert _bytes(a) == _bytes(b)


def test_jpeg_changes_image():
    base = _checkerboard()
    a = augment_image(base, rng=random.Random("j"), jpeg=20)
    assert _bytes(a) != _bytes(base)
    assert a.mode == "RGB"


def test_no_degradation_returns_rgb_copy_unchanged():
    base = _checkerboard()
    out = augment_image(base, rng=random.Random("n"))
    assert _bytes(out) == _bytes(base)


# --- meta tokens -----------------------------------------------------------


def test_degradation_tokens_ordered_and_skips_none():
    tokens = degradation_tokens({"rotate": 2.0, "blur": None, "noise": 8.0, "jpeg": 40})
    assert tokens == ["rotate<=2.0", "noise=8.0", "jpeg_q40"]


# --- corpus driver ---------------------------------------------------------


def _make_corpus(root, ids=("0000", "0001")):
    for sid in ids:
        d = root / sid
        d.mkdir(parents=True)
        _checkerboard().save(d / "image.png")
        (d / "reference.musicxml").write_text(f"<score id='{sid}'/>")
        (d / "meta.yaml").write_text(yaml.safe_dump({"type": "engraved", "source": "x"}))
    return root


def test_augment_corpus_writes_parallel_corpus(tmp_path):
    src = _make_corpus(tmp_path / "src")
    out = tmp_path / "out"
    n = augment_corpus(src, out, degradations={"blur": 1.5, "jpeg": 50}, seed=7)
    assert n == 2

    for sid in ("0000", "0001"):
        sample = out / sid
        assert (sample / "image.png").is_file()
        # reference copied verbatim
        assert (sample / "reference.musicxml").read_text() == f"<score id='{sid}'/>"
        meta = yaml.safe_load((sample / "meta.yaml").read_text())
        assert meta["degradations"] == ["blur=1.5", "jpeg_q50"]
        assert meta["augmented_from"] == str(src)
        assert meta["augment_seed"] == 7
        # original meta fields preserved
        assert meta["type"] == "engraved"


def test_augment_corpus_refuses_in_place(tmp_path):
    # out == src would degrade the source images in place — refused up front.
    src = _make_corpus(tmp_path / "src", ids=("0000",))
    before = (src / "0000" / "image.png").read_bytes()
    with pytest.raises(ValueError):
        augment_corpus(src, src, degradations={"blur": 1.0}, seed=0)
    assert (src / "0000" / "image.png").read_bytes() == before


def test_augment_corpus_does_not_mutate_source(tmp_path):
    src = _make_corpus(tmp_path / "src", ids=("0000",))
    before = (src / "0000" / "image.png").read_bytes()
    augment_corpus(src, tmp_path / "out", degradations={"noise": 30.0}, seed=0)
    assert (src / "0000" / "image.png").read_bytes() == before


def test_augment_corpus_deterministic_across_runs(tmp_path):
    src = _make_corpus(tmp_path / "src", ids=("0000",))
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    augment_corpus(src, out_a, degradations={"noise": 25.0, "rotate": 3.0}, seed=42)
    augment_corpus(src, out_b, degradations={"noise": 25.0, "rotate": 3.0}, seed=42)
    assert (out_a / "0000" / "image.png").read_bytes() == (out_b / "0000" / "image.png").read_bytes()
