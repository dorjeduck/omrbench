"""Image degradation for synthetic corpora — robustness probing, engine-free.

`augment_corpus` reads a corpus and writes a *new* sibling corpus whose images
have been degraded, copying each sample's ``reference.musicxml`` unchanged and
recording the applied degradations in ``meta.yaml``. It never mutates the source
and never mixes degraded with clean output — keep the result in its own corpus
dir and report it separately (it stays the same kind as its source).

This is deliberately *not* a resolution fix: every degradation here makes the
image harder, not sharper. It measures how an engine's accuracy holds up under
realistic scan artifacts, which is what lets the otherwise-optimistic synthetic
corpora earn their keep.

The transforms are Pillow-only and deterministic: given a seed, the same corpus
augments to byte-identical images, and a sample's randomness is derived from the
global seed plus its id, so adding samples does not perturb existing ones. The
fixed apply order is rotate -> blur -> noise -> jpeg (the JPEG roundtrip last, so
its blocking sits on top like a final scan/save).
"""

from __future__ import annotations

import io
import random
import shutil
from pathlib import Path

import yaml
from PIL import Image, ImageChops, ImageFilter

from omrbench.corpus import discover

_WHITE = (255, 255, 255)


def _rotate(img: Image.Image, degrees: float, rng: random.Random) -> Image.Image:
    # a per-sample angle within +/- degrees, on a white background, canvas grown
    # so nothing is clipped
    angle = rng.uniform(-degrees, degrees)
    return img.rotate(angle, expand=True, fillcolor=_WHITE)


def _blur(img: Image.Image, radius: float) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def _noise(img: Image.Image, magnitude: float, rng: random.Random) -> Image.Image:
    # zero-mean uniform luminance noise: a deterministic noise plane centered at
    # 128 (so it adds as a signed delta of +/- magnitude) replicated across RGB.
    w, h = img.size
    plane = Image.frombytes("L", (w, h), rng.randbytes(w * h))
    # map the uniform [0,255] plane to a +/- magnitude delta centered on 128
    table = [int(round((v - 127.5) / 127.5 * magnitude)) + 128 for v in range(256)]
    plane = plane.point(table)
    return ImageChops.add(img, plane.convert("RGB"), scale=1.0, offset=-128)


def _jpeg(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def augment_image(
    img: Image.Image,
    *,
    rng: random.Random,
    rotate: float | None = None,
    blur: float | None = None,
    noise: float | None = None,
    jpeg: int | None = None,
) -> Image.Image:
    """Apply the enabled degradations in fixed order, returning a new RGB image."""
    img = img.convert("RGB")
    if rotate is not None:
        img = _rotate(img, rotate, rng)
    if blur is not None:
        img = _blur(img, blur)
    if noise is not None:
        img = _noise(img, noise, rng)
    if jpeg is not None:
        img = _jpeg(img, jpeg)
    return img


def degradation_tokens(degradations: dict) -> list[str]:
    """Compact, ordered record of applied degradations for a sample's meta.yaml."""
    tokens: list[str] = []
    if degradations.get("rotate") is not None:
        tokens.append(f"rotate<={degradations['rotate']}")
    if degradations.get("blur") is not None:
        tokens.append(f"blur={degradations['blur']}")
    if degradations.get("noise") is not None:
        tokens.append(f"noise={degradations['noise']}")
    if degradations.get("jpeg") is not None:
        tokens.append(f"jpeg_q{degradations['jpeg']}")
    return tokens


def augment_corpus(
    corpus_dir: Path,
    out_dir: Path,
    *,
    degradations: dict,
    seed: int = 0,
) -> int:
    """Write a degraded copy of ``corpus_dir`` to ``out_dir`` and return the
    number of samples written. ``degradations`` is a dict with any of the keys
    rotate/blur/noise/jpeg (None = skip)."""
    corpus_dir = Path(corpus_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tokens = degradation_tokens(degradations)

    count = 0
    for sample in discover(corpus_dir):
        src_image = sample.image
        if src_image is None:
            continue
        rng = random.Random(f"{seed}:{sample.id}")
        augmented = augment_image(
            Image.open(src_image),
            rng=rng,
            rotate=degradations.get("rotate"),
            blur=degradations.get("blur"),
            noise=degradations.get("noise"),
            jpeg=degradations.get("jpeg"),
        )

        sample_out = out_dir / sample.id
        sample_out.mkdir(exist_ok=True)
        augmented.save(sample_out / "image.png")

        reference = sample.reference_musicxml
        if reference.exists():
            shutil.copy(reference, sample_out / "reference.musicxml")

        meta = sample.meta
        meta["degradations"] = tokens
        meta["augmented_from"] = str(corpus_dir)
        meta["augment_seed"] = seed
        (sample_out / "meta.yaml").write_text(yaml.safe_dump(meta))
        count += 1
    return count
