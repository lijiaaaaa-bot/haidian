#!/usr/bin/env python3
"""Sync site_boundary.geojson and key_areas.geojson from upgraded provisional boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

REPO = Path(__file__).resolve().parents[1]
UPGRADED = REPO / "brief/site-package/geometry/provisional_boundaries_upgraded.geojson"

TR = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)

SITE_SOURCE_ID = "PROV-SITE-001"
KEY_IDS = ("PROV-KEY-001", "PROV-KEY-002", "PROV-KEY-003")
MIN_AREA_RATIO = 0.05  # key area after clip must be >= 5% of announced


def area_sqm(geom) -> float:
    return transform(TR.transform, geom).area


def load_features(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for f in data.get("features", []):
        fid = f.get("id") or f.get("properties", {}).get("id")
        if fid:
            out[str(fid)] = f
    return out


def write_geojson(path: Path, name: str, features: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "name": name, "features": features}
    path.write_text(json.dumps(fc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission_dir", type=Path,
                        help="e.g. submissions/lijiaaaaa-bot/jingzhang-zhimai-belt")
    parser.add_argument("--source", type=Path, default=UPGRADED)
    args = parser.parse_args()

    sub = args.submission_dir if args.submission_dir.is_absolute() else REPO / args.submission_dir
    geo = sub / "geometry"
    if not sub.is_dir():
        print(f"ERROR: submission dir not found: {sub}", file=sys.stderr)
        return 1

    feats = load_features(args.source)
    if SITE_SOURCE_ID not in feats:
        print(f"ERROR: missing {SITE_SOURCE_ID} in {args.source}", file=sys.stderr)
        return 1
    for kid in KEY_IDS:
        if kid not in feats:
            print(f"ERROR: missing {kid} in {args.source}", file=sys.stderr)
            return 1

    site_feat = deepcopy(feats[SITE_SOURCE_ID])
    props = site_feat.setdefault("properties", {})
    props["id"] = "SITE-001"
    site_feat["id"] = "SITE-001"
    props["source_id"] = "PROVISIONAL-BOUNDARY-UPGRADED-TEXT-CONSTRAINED"
    props["layer"] = "SITE_BOUNDARY"
    site_geom = shape(site_feat["geometry"]).buffer(0)
    props["area_sqm_calculated"] = round(area_sqm(site_geom), 3)

    write_geojson(geo / "site_boundary.geojson", "site_boundary_upgraded", [site_feat])

    key_features = []
    for kid in KEY_IDS:
        kf = deepcopy(feats[kid])
        kgeom_full = shape(kf["geometry"]).buffer(0)
        kgeom = kgeom_full.intersection(site_geom)
        if kgeom.is_empty:
            print(f"ERROR: {kid} has empty intersection with SITE", file=sys.stderr)
            return 1
        full_area = area_sqm(kgeom_full)
        clipped_area = area_sqm(kgeom)
        # Keep full key polygon when site provisional boundary under-covers announced key area
        if clipped_area < full_area * 0.95:
            kgeom = kgeom_full
            clipped_area = full_area
        announced = kf.get("properties", {}).get("announced_area_sqm") or kf.get("properties", {}).get("area_sqm_declared")
        if announced and clipped_area < float(announced) * MIN_AREA_RATIO:
            print(f"ERROR: {kid} clipped area {clipped_area:.0f} m² < 5% of announced {announced}", file=sys.stderr)
            return 1
        kf["geometry"] = json.loads(json.dumps(kgeom.__geo_interface__))
        kf.setdefault("properties", {})["area_sqm_calculated"] = round(clipped_area, 3)
        kf["properties"]["layer"] = "KEY_AREA"
        key_features.append(kf)

    write_geojson(geo / "key_areas.geojson", "key_areas_official", key_features)
    print(f"Wrote site_boundary.geojson + key_areas.geojson ({len(key_features)} keys) -> {geo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
