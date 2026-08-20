#!/usr/bin/env python3
"""Clip editable design layers to site_boundary (EPSG:4548)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

REPO = Path(__file__).resolve().parents[1]
LAYERS = ["land_use", "buildings", "green_space", "public_space", "phasing"]
TR = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)
TR_INV = Transformer.from_crs("EPSG:4548", "EPSG:4326", always_xy=True)


def to4548(g):
    return transform(TR.transform, g)


def to4326(g):
    return transform(TR_INV.transform, g)


def clip_fc(path: Path, site_clip4548) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for feat in data.get("features", []):
        g = shape(feat["geometry"]).buffer(0)
        g4548 = to4548(g)
        clipped4548 = g4548.intersection(site_clip4548)
        if clipped4548.is_empty:
            continue
        try:
            shrunk = clipped4548.buffer(-0.5)
            if not shrunk.is_empty and shrunk.area > clipped4548.area * 0.98:
                clipped4548 = shrunk
        except Exception:
            pass
        clipped = to4326(clipped4548).buffer(0)
        if not g.equals(clipped):
            feat["geometry"] = mapping(clipped)
            n += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission_dir", type=Path)
    args = parser.parse_args()
    sub = args.submission_dir if args.submission_dir.is_absolute() else REPO / args.submission_dir
    site = shape(json.loads((sub / "geometry/site_boundary.geojson").read_text())["features"][0]["geometry"]).buffer(0)
    site_clip = to4548(site).buffer(1.0)
    total = sum(clip_fc(sub / "geometry" / f"{layer}.geojson", site_clip)
                for layer in LAYERS if (sub / "geometry" / f"{layer}.geojson").is_file())
    print(f"Clipped {total} features to site_boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
