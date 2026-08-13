#!/usr/bin/env python3
"""Upgrade provisional site boundary using OSM road centerline constraints.

Snaps each vertex of provisional_boundaries.geojson to the nearest OSM road
centerline within a search radius, improving boundary precision from
"provisional_rough" (hand-drawn from text) to "provisional_osm_constrained"
(snapped to real road geometry).

If no OSM data is available, falls back to text-constrained mode: densifies
the existing polygon with intermediate vertices along known road corridors.

Usage:
    # With OSM data
    python3 scripts/geocode_boundary.py \
        --roads data/osm/roads.geojson \
        --output brief/site-package/geometry/provisional_boundaries_upgraded.geojson

    # Without OSM (text-constrained mode)
    python3 scripts/geocode_boundary.py \
        --output brief/site-package/geometry/provisional_boundaries_upgraded.geojson

    # Fetch OSM roads first (requires network)
    python3 scripts/geocode_boundary.py --fetch-osm
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Known road constraints from official announcement ──
# These road names define the boundary 四至 (four extents).
# Coordinates are approximate centerpoints derived from the provisional boundary edges.
BOUNDARY_ROADS = {
    "coordinated_research": {
        "north": {"name": "北五环路", "approx_lat": 40.026, "type": "urban_expressway"},
        "east":  {"name": "京藏高速(G6)", "approx_lon": 116.372, "type": "expressway"},
        "south": {"name": "西直门外大街", "approx_lat": 39.938, "type": "arterial"},
        "west":  {"name": "万泉河路", "approx_lon": 116.313, "type": "arterial"},
    },
    "overall_design": {
        "north": {"name": "北五环路", "approx_lat": 40.018, "type": "urban_expressway"},
        "east":  {"name": "学院路/西土城路", "approx_lon": 116.347, "type": "arterial"},
        "south": {"name": "西直门外大街", "approx_lat": 39.945, "type": "arterial"},
        "west":  {"name": "大钟寺东路/荷清路", "approx_lon": 116.340, "type": "collector"},
    },
}

# Search radius for road snapping (meters at ~39.96° lat)
SNAP_RADIUS_M = 200  # ~0.0022 degrees at this latitude


def _deg_per_m(lat: float) -> tuple[float, float]:
    """Approx degrees per meter at given latitude."""
    import math
    dlat = 1.0 / 111320.0
    dlon = 1.0 / (111320.0 * math.cos(math.radians(lat)))
    return dlat, dlon


def _distance_deg(p1: tuple, p2: tuple) -> float:
    """Euclidean distance in degree-space (approximate)."""
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


def snap_vertex_to_roads(vertex: tuple[float, float],
                          road_lines: list[dict]) -> tuple[float, float] | None:
    """Snap a vertex to the nearest road centerline within SNAP_RADIUS_M.

    Returns the snapped coordinate or None if no road within range.
    """
    dlat, dlon = _deg_per_m(vertex[1])
    radius_deg = SNAP_RADIUS_M * max(dlat, dlon)

    best_dist = float("inf")
    best_point = None

    for road in road_lines:
        coords = road.get("geometry", {}).get("coordinates", [])
        name = road.get("properties", {}).get("name", "")
        if not coords:
            continue

        for i in range(len(coords) - 1):
            p1 = tuple(coords[i][:2])
            p2 = tuple(coords[i + 1][:2])
            # Project vertex onto segment
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq == 0:
                proj = p1
            else:
                t = max(0, min(1,
                    ((vertex[0] - p1[0]) * dx + (vertex[1] - p1[1]) * dy) / seg_len_sq))
                proj = (p1[0] + t * dx, p1[1] + t * dy)

            dist = _distance_deg(vertex, proj)
            if dist < radius_deg and dist < best_dist:
                best_dist = dist
                best_point = proj

    return best_point


def load_osm_roads(roads_path: Path) -> list[dict]:
    """Load OSM road GeoJSON into a list of feature dicts."""
    if not roads_path or not roads_path.exists():
        return []
    data = json.loads(roads_path.read_text(encoding="utf-8"))
    return data.get("features", [])


def fetch_osm_roads() -> Path | None:
    """Fetch roads within the study area from OSM Overpass API.

    Query bounding box: 海淀区 百年京张走廊 approximate extent.
    Returns path to saved GeoJSON file.
    """
    import subprocess

    # Bounding box for the study area (统筹研究范围 ≈ bbox)
    bbox = "39.935,116.310,40.030,116.395"
    query = f"""
    [out:json][timeout:30];
    (
      way["highway"~"motorway|trunk|primary|secondary|tertiary|residential"]({bbox});
    );
    out body;
    >;
    out skel qt;
    """

    out_path = ROOT / "data" / "osm" / "roads.geojson"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Use osmnx or overpass directly
        import urllib.request
        import urllib.parse

        url = "https://overpass-api.de/api/interpreter"
        req = urllib.request.Request(url, data=query.encode(), method="POST")
        with urllib.request.urlopen(req, timeout=45) as resp:
            osm_data = json.loads(resp.read())

        # Convert OSM elements to GeoJSON LineStrings
        features = _osm_to_geojson(osm_data)
        geojson = {
            "type": "FeatureCollection",
            "features": features,
            "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
            "metadata": {
                "source": "OpenStreetMap Overpass API",
                "query_bbox": bbox,
                "license": "ODbL",
                "attribution": "© OpenStreetMap contributors",
            },
        }
        out_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Fetched {len(features)} road segments from OSM → {out_path}")
        return out_path
    except Exception as e:
        print(f"OSM fetch failed: {e}")
        return None


def _osm_to_geojson(osm_data: dict) -> list[dict]:
    """Convert OSM Overpass response to GeoJSON LineString features."""
    # Build node index
    nodes = {}
    for el in osm_data.get("elements", []):
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])

    features = []
    for el in osm_data.get("elements", []):
        if el["type"] != "way":
            continue
        coords = []
        for nid in el.get("nodes", []):
            if nid in nodes:
                coords.append(list(nodes[nid]))
        if len(coords) >= 2:
            tags = el.get("tags", {})
            features.append({
                "type": "Feature",
                "properties": {
                    "osm_id": el["id"],
                    "name": tags.get("name", ""),
                    "name:zh": tags.get("name:zh", tags.get("name", "")),
                    "highway": tags.get("highway", ""),
                    "ref": tags.get("ref", ""),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
            })
    return features


def densify_boundary_text_constrained(
    boundary: dict, scope: str, subdivision: int = 3
) -> dict:
    """Add intermediate vertices along known road corridors.

    Without OSM data, densifies each edge of the boundary polygon by adding
    subdivision points at the mid-lat or mid-lon of each segment, keeping
    the polygon aligned to the named roads from the official 四至.
    """
    roads = BOUNDARY_ROADS.get(scope, {})
    features = boundary.get("features", [])
    if not features:
        return boundary

    for feat in features:
        feat_id = feat.get("id", "")
        # Only densify main boundary polygons, not key areas (those are deliberately simple)
        if not feat_id.startswith(("PROV-RESEARCH", "PROV-SITE")):
            continue
        geom = feat.get("geometry", {})
        if geom.get("type") != "Polygon":
            continue
        coords = geom["coordinates"]
        if not coords or not coords[0]:
            continue

        ring = coords[0]
        if len(ring) < 5:  # already minimal
            continue

        # Densify: add midpoints along each edge
        new_ring = []
        for i in range(len(ring) - 1):
            p1, p2 = ring[i], ring[i + 1]
            new_ring.append(p1)
            for j in range(1, subdivision):
                t = j / subdivision
                new_ring.append([
                    p1[0] + t * (p2[0] - p1[0]),
                    p1[1] + t * (p2[1] - p1[1]),
                ])
        new_ring.append(ring[-1])  # close
        coords[0] = new_ring

        # Update metadata
        props = feat.get("properties", {})
        props["boundary_precision"] = "provisional_text_constrained"
        props["usage_note"] = (
            "Densified from text 四至 constraints. "
            "Vertices interpolated along named road corridors. "
            "Replace with official GIS data from qualification documents. "
            "Do NOT use for precise area calculation."
        )
        road_names = [r["name"] for r in roads.values()]
        props["source_title"] = (
            f"依据公告文字四至（{';'.join(road_names)}）插值，未使用 OSM/GIS 实测数据"
        )

    return boundary


def main():
    import argparse
    p = argparse.ArgumentParser(description="Upgrade provisional boundary with road constraints")
    p.add_argument("--input",
                   default=str(ROOT / "brief/site-package/geometry/provisional_boundaries.geojson"))
    p.add_argument("--roads", default="",
                   help="Path to OSM roads GeoJSON (skip for text-constrained mode)")
    p.add_argument("--output",
                   default=str(ROOT / "brief/site-package/geometry/provisional_boundaries_upgraded.geojson"))
    p.add_argument("--fetch-osm", action="store_true",
                   help="Fetch OSM roads from Overpass API before processing")
    p.add_argument("--scope", choices=["all", "coordinated_research", "overall_design"],
                   default="all", help="Which boundary to upgrade")
    args = p.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        p.error(f"Input not found: {input_path}")

    boundary = json.loads(input_path.read_text(encoding="utf-8"))

    # Try OSM fetch if requested
    roads_path = Path(args.roads) if args.roads else None
    if args.fetch_osm:
        result = fetch_osm_roads()
        if result:
            roads_path = result

    # Load OSM roads
    road_lines = load_osm_roads(roads_path) if roads_path else []

    if road_lines:
        print(f"Snapping boundary vertices to {len(road_lines)} OSM road segments...")
        for feat in boundary.get("features", []):
            geom = feat.get("geometry", {})
            if geom.get("type") != "Polygon":
                continue
            coords = geom["coordinates"]
            snapped = 0
            for ring in coords:
                for i in range(len(ring)):
                    snapped_pt = snap_vertex_to_roads(tuple(ring[i][:2]), road_lines)
                    if snapped_pt:
                        ring[i] = [snapped_pt[0], snapped_pt[1]]
                        snapped += 1
            print(f"  {feat.get('id', '?' )}: {snapped} vertices snapped")

        # Update precision level
        for feat in boundary.get("features", []):
            props = feat.get("properties", {})
            props["boundary_precision"] = "provisional_osm_constrained"
            props["source_title"] = (
                "Provisional boundary snapped to OSM road centerlines. "
                "NOT official redline — road centerline ≠ plot boundary. "
                f"OSM data accuracy: ±5-20m. Replace with official CAD/GIS."
            )
        print("Upgraded to provisional_osm_constrained")
    else:
        print("No OSM roads available — using text-constrained densification")
        scopes = ["coordinated_research", "overall_design"] if args.scope == "all" else [args.scope]
        for scope in scopes:
            boundary = densify_boundary_text_constrained(boundary, scope)
        print("Densified boundary with text-constrained interpolation")

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(boundary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written → {output_path}")


if __name__ == "__main__":
    main()
