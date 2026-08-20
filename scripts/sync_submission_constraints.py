#!/usr/bin/env python3
"""Clip tianditu rail (LRRL) and water (HYDL) into submission constraints.geojson."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shapely.geometry import MultiLineString, shape
from shapely.ops import transform, unary_union

from pyproj import Transformer

REPO = Path(__file__).resolve().parents[1]
TIANDITU = REPO / "data/processed/tianditu_wfs_beijing.geojson"

TR = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)
TR_INV = Transformer.from_crs("EPSG:4548", "EPSG:4326", always_xy=True)


def to4548(g):
    return transform(TR.transform, g)


def to4326(g):
    return transform(TR_INV.transform, g)


def lines_from_features(features: list, layer: str, site4548, buffer_m: float = 800):
    parts = []
    for f in features:
        if f.get("properties", {}).get("tdt_layer") != layer:
            continue
        g = shape(f["geometry"])
        g4548 = to4548(g)
        if g4548.intersects(site4548.buffer(buffer_m)):
            clipped = g4548.intersection(site4548.buffer(buffer_m))
            if clipped.is_empty:
                continue
            if clipped.geom_type == "LineString":
                parts.append(clipped)
            elif clipped.geom_type == "MultiLineString":
                parts.extend(clipped.geoms)
            elif clipped.geom_type == "GeometryCollection":
                for sub in clipped.geoms:
                    if sub.geom_type in ("LineString", "MultiLineString"):
                        parts.extend(sub.geoms if sub.geom_type == "MultiLineString" else [sub])
    return parts


def merge_lines(parts) -> MultiLineString | None:
    if not parts:
        return None
    merged = unary_union(parts)
    if merged.is_empty:
        return None
    if merged.geom_type == "LineString":
        return MultiLineString([merged])
    if merged.geom_type == "MultiLineString":
        return merged
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission_dir", type=Path)
    parser.add_argument("--tianditu", type=Path, default=TIANDITU)
    args = parser.parse_args()

    sub = args.submission_dir if args.submission_dir.is_absolute() else REPO / args.submission_dir
    site_path = sub / "geometry" / "site_boundary.geojson"
    out_path = sub / "geometry" / "constraints.geojson"
    if not site_path.is_file():
        print(f"ERROR: run sync_submission_boundary first: {site_path}", file=sys.stderr)
        return 1
    if not args.tianditu.is_file():
        print(f"ERROR: missing tianditu: {args.tianditu}", file=sys.stderr)
        return 1

    site = shape(json.loads(site_path.read_text())["features"][0]["geometry"]).buffer(0)
    site4548 = to4548(site)
    tdt = json.loads(args.tianditu.read_text(encoding="utf-8"))["features"]

    rail_parts = lines_from_features(tdt, "LRRL", site4548, buffer_m=600)
    water_parts = lines_from_features(tdt, "HYDL", site4548, buffer_m=400)
    rail_mls = merge_lines(rail_parts)
    water_mls = merge_lines(water_parts)

    if rail_mls is None:
        print("ERROR: no rail (LRRL) segments clipped to site", file=sys.stderr)
        return 1
    if water_mls is None:
        print("ERROR: no water (HYDL) segments clipped to site", file=sys.stderr)
        return 1

    features = [
        {
            "type": "Feature",
            "id": "CONSTRAINTS-001",
            "properties": {
                "id": "CONSTRAINTS-001",
                "layer": "ROAD_CENTERLINE",
                "source_type": "official_open_data",
                "confidence": "medium",
                "geometry_role": "provisional_constraint",
                "constraint_type": "existing_rail",
                "official_boundary": False,
                "boundary_precision": "provisional_rough",
                "name_zh": "京张铁路遗址走廊（天地图 LRRL 线位示意）",
                "source_id": "DATA-SRC-TIANDITU-WFS-1M",
                "usage_note": "天地图 1:100万铁路线位；正式轨道红线以官方资料为准",
            },
            "geometry": json.loads(json.dumps(to4326(rail_mls).__geo_interface__)),
        },
        {
            "type": "Feature",
            "id": "CONSTRAINTS-002",
            "properties": {
                "id": "CONSTRAINTS-002",
                "layer": "ROAD_CENTERLINE",
                "source_type": "official_open_data",
                "confidence": "medium",
                "geometry_role": "provisional_constraint",
                "constraint_type": "existing_water",
                "official_boundary": False,
                "boundary_precision": "provisional_rough",
                "name_zh": "清河/小月河水系（天地图 HYDL 线位示意）",
                "source_id": "DATA-SRC-TIANDITU-WFS-1M",
                "usage_note": "天地图 1:100万水系线位；正式蓝线以官方资料为准",
            },
            "geometry": json.loads(json.dumps(to4326(water_mls).__geo_interface__)),
        },
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "name": "constraints_real", "features": features}
    out_path.write_text(json.dumps(fc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote constraints.geojson (rail lines={len(rail_parts)}, water lines={len(water_parts)}) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
