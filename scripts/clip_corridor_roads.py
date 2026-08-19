#!/usr/bin/env python3
"""Clip OSM + tianditu roads into submission geometry/roads.geojson."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, shape
from shapely.ops import transform

REPO = Path(__file__).resolve().parents[1]
OSM = REPO / "data/processed/osm_road_network.geojson"
TIANDITU = REPO / "data/processed/tianditu_wfs_beijing.geojson"

TR = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)
TR_INV = Transformer.from_crs("EPSG:4548", "EPSG:4326", always_xy=True)

GREENWAY_CLASSES = {"footway", "pedestrian", "path", "cycleway", "steps"}
ARTERIAL_CLASSES = {"primary", "secondary", "tertiary", "trunk", "motorway", "expressway"}
MIN_FEATURES = 3
DEFAULT_MAX_FEATURES = 120


def to4548(g):
    return transform(TR.transform, g)


def to4326(g):
    return transform(TR_INV.transform, g)


def classify_road(props: dict) -> str:
    rc = (props.get("road_class") or props.get("highway_tag") or "").lower()
    if rc in GREENWAY_CLASSES:
        return "greenway"
    if rc in ARTERIAL_CLASSES:
        return "arterial"
    if rc in ("transit", "rail", "subway"):
        return "transit_connection"
    if rc in ("service", "residential", "unclassified", "living_street"):
        return "local"
    return "local"


def clip_line_features(source_features: list, site4548, buffer_m: float, source_label: str) -> list[dict]:
    out = []
    buf = site4548.buffer(buffer_m)
    for i, f in enumerate(source_features):
        g = shape(f["geometry"])
        if g.geom_type not in ("LineString", "MultiLineString"):
            continue
        g4548 = to4548(g)
        if not g4548.intersects(buf):
            continue
        clipped = g4548.intersection(buf)
        if clipped.is_empty:
            continue
        lines = []
        if clipped.geom_type == "LineString":
            lines = [clipped]
        elif clipped.geom_type == "MultiLineString":
            lines = list(clipped.geoms)
        elif clipped.geom_type == "GeometryCollection":
            for sub in clipped.geoms:
                if sub.geom_type == "LineString":
                    lines.append(sub)
                elif sub.geom_type == "MultiLineString":
                    lines.extend(sub.geoms)
        for j, ln in enumerate(lines):
            if ln.length < 20:  # skip tiny slivers (<20m)
                continue
            rid = f"ROAD-{source_label}-{len(out)+1:03d}"
            props = dict(f.get("properties") or {})
            road_class = classify_road(props)
            out.append({
                "type": "Feature",
                "id": rid,
                "properties": {
                    "id": rid,
                    "layer": "ROAD_CENTERLINE",
                    "source_type": props.get("source_type", "openstreetmap"),
                    "confidence": "medium",
                    "geometry_role": "design_proposal",
                    "road_class": road_class,
                    "name_zh": props.get("name") or props.get("name_zh") or f"走廊道路-{len(out)+1}",
                    "source_id": props.get("source_id", f"DATA-SRC-OSM-{source_label}"),
                    "official_boundary": False,
                    "provisional_note": "OSM/天地图裁剪至 SITE；正式道路红线待官方数据",
                },
                "geometry": json.loads(json.dumps(to4326(ln).__geo_interface__)),
            })
    return out


def prioritize_roads(features: list[dict], max_features: int) -> list[dict]:
    """Keep greenway + arterial first, then longest local segments."""
    if len(features) <= max_features:
        return features

    def sort_key(f: dict) -> tuple:
        rc = f["properties"].get("road_class", "local")
        priority = {"greenway": 0, "transit_connection": 1, "arterial": 2}.get(rc, 3)
        g = shape(f["geometry"])
        length = to4548(g).length
        return (priority, -length)

    ranked = sorted(features, key=sort_key)
    kept = ranked[:max_features]
    # Ensure required classes survive truncation
    for required in ("greenway", "arterial"):
        if not any(f["properties"].get("road_class") == required for f in kept):
            donor = next((f for f in ranked if f["properties"].get("road_class") == required), None)
            if donor and donor not in kept:
                kept[-1] = donor
    return kept


def ensure_greenway(features: list[dict]) -> list[dict]:
    """Ensure at least one greenway — tag longest footway/pedestrian or add Jingzhang corridor label."""
    if any(f["properties"].get("road_class") == "greenway" for f in features):
        return features
    candidates = [f for f in features if f.get("properties", {}).get("road_class") == "local"]
    if candidates:
        f = candidates[0]
        f["properties"]["road_class"] = "greenway"
        f["properties"]["name_zh"] = "京张遗址公园慢行廊道（示意）"
        f["properties"]["corridor_role"] = "jingzhang_greenway"
    return features


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission_dir", type=Path)
    parser.add_argument("--osm", type=Path, default=OSM)
    parser.add_argument("--tianditu", type=Path, default=TIANDITU)
    parser.add_argument("--max-features", type=int, default=DEFAULT_MAX_FEATURES)
    args = parser.parse_args()

    sub = args.submission_dir if args.submission_dir.is_absolute() else REPO / args.submission_dir
    site_path = sub / "geometry" / "site_boundary.geojson"
    out_path = sub / "geometry" / "roads.geojson"
    if not site_path.is_file():
        print("ERROR: site_boundary.geojson missing; run sync_submission_boundary.py", file=sys.stderr)
        return 1

    site = shape(json.loads(site_path.read_text())["features"][0]["geometry"]).buffer(0)
    site4548 = to4548(site)

    osm_feats = json.loads(args.osm.read_text())["features"] if args.osm.is_file() else []
    tdt_feats = [f for f in json.loads(args.tianditu.read_text())["features"]
                 if f.get("properties", {}).get("tdt_layer") == "LRDL"] if args.tianditu.is_file() else []

    roads = clip_line_features(osm_feats, site4548, buffer_m=150, source_label="OSM")
    roads += clip_line_features(tdt_feats, site4548, buffer_m=200, source_label="TDT")
    roads = ensure_greenway(roads)
    roads = prioritize_roads(roads, args.max_features)

    if len(roads) < MIN_FEATURES:
        print(f"ERROR: only {len(roads)} road features after clip; need >= {MIN_FEATURES}", file=sys.stderr)
        return 1
    has_green = any(r["properties"].get("road_class") == "greenway" for r in roads)
    has_arterial = any(r["properties"].get("road_class") in ("arterial", "transit_connection") for r in roads)
    if not has_green:
        print("ERROR: no greenway in roads.geojson after clip", file=sys.stderr)
        return 1
    if not has_arterial:
        print("ERROR: no arterial/transit_connection in roads.geojson after clip", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "name": "roads_corridor", "features": roads}
    out_path.write_text(json.dumps(fc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote roads.geojson: {len(roads)} features (greenway={has_green}, arterial={has_arterial})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
