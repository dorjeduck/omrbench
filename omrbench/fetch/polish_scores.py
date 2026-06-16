"""Fetch the btrkeks/polish-scores Tier-2 corpus into omrbench layout.

112 real historical scans with dual ground truth (MusicXML + **kern), openly
downloadable, license "evaluation only — do not train". See corpus/tier2_real/
README for the propagated restriction.

The HF column names are auto-detected (the card does not pin them), so this is
defensive: it picks the first column matching each role and reports its choice.
Verify the mapping on first run.

Requires the optional 'fetch' extra:  pip install 'omrbench[fetch]'
"""

from __future__ import annotations

from pathlib import Path

import yaml

_IMAGE_KEYS = ("image", "img", "scan", "page")
_MUSICXML_KEYS = ("musicxml", "music_xml", "xml", "mxml")

_LICENSE_NOTE = "evaluation only — do not include in training data (btrkeks/polish-scores)"


def _pick(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {c.lower(): c for c in columns}
    for cand in candidates:
        for low, original in lowered.items():
            if cand in low:
                return original
    return None


def fetch(dest: Path, split: str = "test") -> int:
    from datasets import load_dataset  # type: ignore[import-untyped]

    ds = load_dataset("btrkeks/polish-scores")
    if split not in ds:
        split = next(iter(ds))
    data = ds[split]

    columns = list(data.features)
    image_key = _pick(columns, _IMAGE_KEYS)
    musicxml_key = _pick(columns, _MUSICXML_KEYS)
    print(f"columns={columns}")
    print(f"mapped image={image_key} musicxml={musicxml_key}")
    if image_key is None or musicxml_key is None:
        raise RuntimeError(
            "could not map image/musicxml columns; inspect the printed columns "
            "and adjust _IMAGE_KEYS/_MUSICXML_KEYS in this file."
        )

    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for i, row in enumerate(data):
        sample_id = f"{i:04d}"
        sample_dir = dest / sample_id
        sample_dir.mkdir(exist_ok=True)

        row[image_key].save(sample_dir / "image.png")
        _write_text(sample_dir / "reference.musicxml", row[musicxml_key])
        (sample_dir / "meta.yaml").write_text(
            yaml.safe_dump(
                {
                    "tier": "tier2_real",
                    "source": "btrkeks/polish-scores",
                    "type": "real_scan",
                    "license": _LICENSE_NOTE,
                }
            )
        )
        count += 1
    return count


def _write_text(path: Path, value: object) -> None:
    text = value.decode("utf-8") if isinstance(value, bytes) else str(value)
    path.write_text(text)
