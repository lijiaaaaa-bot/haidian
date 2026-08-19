#!/usr/bin/env python3
"""Fail-fast prerequisite checks before submission upgrade pipeline.

Exits 0 only when data + tooling required for the no-fallback upgrade path exist.
UST is required for figure generation but may be absent on Cloud VM — use
--skip-ust to allow geometry/data steps only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DEFAULT_UST = Path(os.environ.get("UST_ROOT", "/Users/lijia/Projects/urban-spatial-tooling"))
UPGRADED_BOUNDARY = REPO / "brief/site-package/geometry/provisional_boundaries_upgraded.geojson"
TIANDITU = REPO / "data/processed/tianditu_wfs_beijing.geojson"
OSM_ROADS = REPO / "data/processed/osm_road_network.geojson"

REQUIRED_BOUNDARY_IDS = {"PROV-SITE-001", "PROV-KEY-001", "PROV-KEY-002", "PROV-KEY-003"}
REQUIRED_TDT_LAYERS = {"LRRL", "HYDL"}
MIN_OSM_ROADS = 100


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_python_deps(*, require_geopandas: bool) -> None:
    for name in ("pyproj", "shapely"):
        if importlib.util.find_spec(name) is None:
            _fail(f"Missing Python package '{name}'. Install: python3 -m pip install pyproj shapely")
    if require_geopandas and importlib.util.find_spec("geopandas") is None:
        _fail("Missing geopandas (required for UST figures). Install: python3 -m pip install geopandas")


def check_upgraded_boundary() -> None:
    if not UPGRADED_BOUNDARY.is_file():
        _fail(f"Missing upgraded boundary: {UPGRADED_BOUNDARY}\n"
              "Run: python3 scripts/geocode_boundary.py")
    data = json.loads(UPGRADED_BOUNDARY.read_text(encoding="utf-8"))
    ids = {f.get("id") or f.get("properties", {}).get("id") for f in data.get("features", [])}
    missing = REQUIRED_BOUNDARY_IDS - ids
    if missing:
        _fail(f"Upgraded boundary missing feature ids: {sorted(missing)}")


def check_tianditu() -> None:
    if not TIANDITU.is_file():
        _fail(f"Missing tianditu WFS extract: {TIANDITU}")
    data = json.loads(TIANDITU.read_text(encoding="utf-8"))
    layers = {f.get("properties", {}).get("tdt_layer") for f in data.get("features", [])}
    missing = REQUIRED_TDT_LAYERS - layers
    if missing:
        _fail(f"Tianditu file missing layers {sorted(missing)}; found {sorted(layers)}")


def check_osm() -> None:
    if not OSM_ROADS.is_file():
        _fail(f"Missing OSM road network: {OSM_ROADS}")
    data = json.loads(OSM_ROADS.read_text(encoding="utf-8"))
    n = len(data.get("features", []))
    if n < MIN_OSM_ROADS:
        _fail(f"OSM road network has {n} features; need >= {MIN_OSM_ROADS}")


def check_ust() -> None:
    if not DEFAULT_UST.is_dir():
        _fail(f"UST_ROOT not found: {DEFAULT_UST}\n"
              "Clone urban-spatial-tooling and set UST_ROOT, or run on Mac with UST installed.")
    ust_path = str(DEFAULT_UST)
    if ust_path not in sys.path:
        sys.path.insert(0, ust_path)
    try:
        import src.visualization  # noqa: F401
    except ImportError as exc:
        _fail(f"Cannot import src.visualization from UST_ROOT={DEFAULT_UST}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify submission upgrade prerequisites")
    parser.add_argument("--skip-ust", action="store_true",
                        help="Skip UST check (Cloud VM geometry/data-only runs)")
    args = parser.parse_args()

    check_python_deps(require_geopandas=not args.skip_ust)
    check_upgraded_boundary()
    check_tianditu()
    check_osm()
    if not args.skip_ust:
        check_ust()

    print("OK: all prerequisite checks passed"
          + (" (UST skipped)" if args.skip_ust else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
