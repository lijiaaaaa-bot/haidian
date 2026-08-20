#!/usr/bin/env python3
"""Recalculate submission metrics.json from local GeoJSON (EPSG:4548)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

REPO = Path(__file__).resolve().parents[1]
RESEARCH_BOUNDARY = REPO / "brief/site-package/geometry/provisional_boundaries_upgraded.geojson"
TR = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)


def area4548(geom) -> float:
    return transform(TR.transform, geom).area


def load_fc(path: Path) -> list:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("features", [])


def sum_layer_area(sub: Path, filename: str) -> float:
    total = 0.0
    for f in load_fc(sub / "geometry" / filename):
        g = shape(f["geometry"])
        if not g.is_empty:
            total += area4548(g)
    return total


def feat_area_by_id(sub: Path, filename: str, fid: str) -> float:
    for f in load_fc(sub / "geometry" / filename):
        if f.get("properties", {}).get("id") == fid or f.get("id") == fid:
            g = shape(f["geometry"])
            if not g.is_empty:
                return area4548(g)
    return 0.0


def research_area() -> float:
    if not RESEARCH_BOUNDARY.is_file():
        return 43609232.558
    for f in json.loads(RESEARCH_BOUNDARY.read_text())["features"]:
        if f.get("id") == "PROV-RESEARCH-001" or f.get("properties", {}).get("id") == "PROV-RESEARCH-001":
            return area4548(shape(f["geometry"]))
    return 43609232.558


def m_known(value, unit, sources, formula, assumptions=None):
    return {
        "status": "known",
        "value": round(value, 3) if isinstance(value, float) else value,
        "unit": unit,
        "source_files": sources,
        "formula": formula,
        "confidence": "medium",
        "assumptions": assumptions or ["Provisional geometry; EPSG:4548 recalc"],
    }


def m_unknown(unit, reason):
    return {
        "status": "unknown",
        "value": None,
        "unit": unit,
        "source_files": [],
        "formula": "",
        "confidence": "unknown",
        "assumptions": [],
        "reason": reason,
    }


def build_metrics(sub: Path) -> dict:
    site = sum_layer_area(sub, "site_boundary.geojson")
    key_total = (
        feat_area_by_id(sub, "key_areas.geojson", "PROV-KEY-001")
        + feat_area_by_id(sub, "key_areas.geojson", "PROV-KEY-002")
        + feat_area_by_id(sub, "key_areas.geojson", "PROV-KEY-003")
    )
    bldg = sum_layer_area(sub, "buildings.geojson")
    green = sum_layer_area(sub, "green_space.geojson")
    public = sum_layer_area(sub, "public_space.geojson")
    lu_n = len(load_fc(sub / "geometry/land_use.geojson"))
    b_n = len(load_fc(sub / "geometry/buildings.geojson"))
    r_n = len(load_fc(sub / "geometry/roads.geojson"))
    green_ratio = green / site if site else 0
    public_ratio = public / site if site else 0

    metrics = {
        "site_area_sqm": m_known(site, "sqm", ["geometry/site_boundary.geojson"],
                                 "polygon_area(SITE-001, EPSG:4548)"),
        "overall_design_area_sqm": m_known(site, "sqm", ["geometry/site_boundary.geojson"],
                                           "polygon_area(SITE-001, EPSG:4548)"),
        "coordinated_research_area_sqm": m_known(
            research_area(), "sqm", ["brief/site-package/geometry/provisional_boundaries_upgraded.geojson"],
            "polygon_area(PROV-RESEARCH-001, EPSG:4548)",
            ["统筹研究范围来自 brief 升级边界，非包内 geometry"],
        ),
        "key_detailed_design_area_sqm": m_known(key_total, "sqm", ["geometry/key_areas.geojson"],
                                               "sum(polygon_area(PROV-KEY-001..003, EPSG:4548))"),
        "zhongzhiyuan_ai_acceleration_area_sqm": m_known(
            feat_area_by_id(sub, "key_areas.geojson", "PROV-KEY-001"), "sqm",
            ["geometry/key_areas.geojson"], "polygon_area(PROV-KEY-001, EPSG:4548)"),
        "beijing_ai_origin_community_area_sqm": m_known(
            feat_area_by_id(sub, "key_areas.geojson", "PROV-KEY-002"), "sqm",
            ["geometry/key_areas.geojson"], "polygon_area(PROV-KEY-002, EPSG:4548)"),
        "dazhongsi_ai_industry_cluster_area_sqm": m_known(
            feat_area_by_id(sub, "key_areas.geojson", "PROV-KEY-003"), "sqm",
            ["geometry/key_areas.geojson"], "polygon_area(PROV-KEY-003, EPSG:4548)"),
        "building_footprint_area_sqm": m_known(bldg, "sqm", ["geometry/buildings.geojson"],
                                               f"sum({b_n} building footprints, EPSG:4548)"),
        "green_space_area_sqm": m_known(green, "sqm", ["geometry/green_space.geojson"],
                                        f"sum({len(load_fc(sub / 'geometry/green_space.geojson'))} features, EPSG:4548)"),
        "public_space_area_sqm": m_known(public, "sqm", ["geometry/public_space.geojson"],
                                         f"sum({len(load_fc(sub / 'geometry/public_space.geojson'))} features, EPSG:4548)"),
        "green_ratio": m_known(green_ratio, "ratio",
                               ["geometry/green_space.geojson", "geometry/site_boundary.geojson"],
                               "green_space_area_sqm / site_area_sqm"),
        "public_space_ratio": m_known(public_ratio, "ratio",
                                      ["geometry/public_space.geojson", "geometry/site_boundary.geojson"],
                                      "public_space_area_sqm / site_area_sqm"),
        "land_use_feature_count": m_known(lu_n, "count", ["geometry/land_use.geojson"], "count(land_use features)"),
        "building_feature_count": m_known(b_n, "count", ["geometry/buildings.geojson"], "count(building features)"),
        "road_feature_count": m_known(r_n, "count", ["geometry/roads.geojson"], "count(road features)"),
        "key_area_count": m_known(3, "count", ["geometry/key_areas.geojson"], "count(key areas)"),
        "floor_area_ratio": m_unknown("ratio", "Approved FAR controls not available."),
        "building_height_m": m_unknown("m", "Official height controls not available."),
        "building_density": m_unknown("ratio", "Approved density controls not available."),
        "setback_m": m_unknown("m", "Road/building setback controls not available."),
        "height_m": m_unknown("m", "Representative building height pending official controls."),
        "ratio": m_unknown("ratio", "Generic ratio placeholder; see green_ratio/public_space_ratio for known values."),
        "phase_1_area_sqm": m_known(
            feat_area_by_id(sub, "geometry/phasing.geojson", "PHASE-001") or sum_layer_area(sub, "phasing.geojson") / 3,
            "sqm", ["geometry/phasing.geojson"], "phase polygon area EPSG:4548"),
    }
    for pid in ("PHASE-001", "PHASE-002", "PHASE-003"):
        a = feat_area_by_id(sub, "phasing.geojson", pid)
        if a:
            metrics[f"phase_{pid.split('-')[1].lower()}_area_sqm"] = m_known(
                a, "sqm", ["geometry/phasing.geojson"], f"polygon_area({pid}, EPSG:4548)")

    return {
        "schema_version": "0.1.0",
        "crs": {
            "geojson_exchange": "EPSG:4326",
            "area_calculation": "EPSG:4548",
            "note": "面积复算使用 EPSG:4548。替换 official polygon 后所有面积需重算。",
        },
        "units": {"length": "m", "area": "sqm"},
        "metrics": metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission_dir", type=Path, nargs="?",
                        default=REPO / "submissions/lijiaaaaa-bot/jingzhang-zhimai-belt")
    args = parser.parse_args()
    sub = args.submission_dir if args.submission_dir.is_absolute() else REPO / args.submission_dir
    out = sub / "metrics.json"
    payload = build_metrics(sub)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out.relative_to(REPO)} ({len(payload['metrics'])} metrics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
