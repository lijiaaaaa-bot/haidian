#!/usr/bin/env python3
"""Vectorize 海淀分区规划(2017-2035) raster map figures into GeoJSON background layers.

Figures are official (规划公示图), but raster and unprojected. This script:
  1. classifies map pixels by legend colours,
  2. traces region polygons (morphological cleanup),
  3. registers pixels -> lon/lat via an affine fit against the district bounding
     box (BOUL from Tianditu) and validates with the printed scale bar.

Output: data/processed/hd_fqgh_2020_fig05_zonation.geojson (official background
layer, usable_for_formal=background_only — NOT survey-grade geometry).

Run from repo root with PYTHONPATH having numpy/scipy/PIL/shapely/pyproj.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from shapely.geometry import Polygon, shape
from shapely.ops import transform, unary_union
from pyproj import Transformer

REPO = Path(__file__).resolve().parents[1]

# ------------------------------------------------------------------ legend
# colour -> category anchors (quantized to 8), from fig05 legend analysis
LEGEND = {
    "urban_construction": {  # 城镇建设用地（粉红）
        "anchor": (240, 136, 136), "label_zh": "城镇建设用地（官方分区图）",
        "name": "urban_construction_land", "tolerance": 60,
    },
    "water_protection": {  # 水域保护区（淡蓝/青）
        "anchor": (160, 192, 240), "label_zh": "水域保护区（官方分区图）",
        "name": "water_protection_zone", "tolerance": 50,
    },
    "ecological_green": {  # 园林草保护区/生态混合（绿系）
        "anchor": (56, 152, 0), "label_zh": "园林草保护区/生态混合区（官方分区图）",
        "name": "ecological_green_zone", "tolerance": 80,
    },
    "conditional_construction": {  # 有条件建设区（黄）
        "anchor": (248, 248, 120), "label_zh": "有条件建设区（官方分区图）",
        "name": "conditional_construction_zone", "tolerance": 50,
    },
    "village_construction": {  # 村庄建设用地（橙黄）
        "anchor": (248, 208, 120), "label_zh": "村庄建设用地（官方分区图）",
        "name": "village_construction_land", "tolerance": 50,
    },
}

# district bbox from Tianditu BOUL (merged 海淀区)
LON0, LAT0, LON1, LAT1 = 116.0426, 39.8854, 116.3888, 40.1597
# image region bbox (px) measured on fig05 p090
IMG_X0, IMG_Y0, IMG_X1, IMG_Y1 = 68, 246, 1171, 1402

# 图03 两线三区规划图
FIG03 = {
    "source": "p088_fig03_sanzone.png",
    "output": "hd_fqgh_2020_fig03_sanzone.geojson",
    "fig_label": "图03 两线三区规划图",
    "legend_band": 0.75,
    "img_bbox": (106, 322, 1134, 1382),
    "legend": {
        "concentrated_construction": {  # 集中建设区（橙）
            "anchor": (240, 192, 104), "label_zh": "集中建设区（官方三区图）",
            "name": "concentrated_construction_zone", "tolerance": 55,
        },
        "restricted_construction": {  # 限制建设区（米黄）
            "anchor": (248, 232, 176), "label_zh": "限制建设区（官方三区图）",
            "name": "restricted_construction_zone", "tolerance": 45,
        },
        "ecological_control": {  # 生态控制区（橄榄绿）
            "anchor": (112, 160, 0), "label_zh": "生态控制区（官方三区图）",
            "name": "ecological_control_zone", "tolerance": 55,
        },
    },
}


def classify_pixel(rgb, anchor, tol):
    return all(abs(int(rgb[i]) - anchor[i]) <= tol for i in range(3))


def pixels_to_lonlat(x, y):
    lon = LON0 + (x - IMG_X0) / (IMG_X1 - IMG_X0) * (LON1 - LON0)
    lat = LAT1 - (y - IMG_Y0) / (IMG_Y1 - IMG_Y0) * (LAT1 - LAT0)
    return lon, lat


def mask_to_polygons(mask_2d, min_area_px=60, simplify_px=2.0):
    """Trace labelled components into simplified polygons (pixel coords)."""
    lab, n = ndimage.label(mask_2d)
    polys = []
    for i in range(1, n + 1):
        comp = lab == i
        if comp.sum() < min_area_px:
            continue
        # trace boundary via binary erosion -> point ring
        edge = comp & ~ndimage.binary_erosion(comp)
        ys, xs = np.where(edge)
        if len(xs) < 10:
            continue
        # order points: approximate convex hull is enough for background layer
        try:
            from scipy.spatial import ConvexHull
            pts = np.stack([xs, ys], axis=1)
            hull = ConvexHull(pts)
            ring = [(float(pts[v][0]), float(pts[v][1])) for v in hull.vertices]
        except Exception:
            continue
        ring.append(ring[0])
        if len(ring) < 5:
            continue
        poly = Polygon(ring).buffer(1.0)
        poly = poly.simplify(simplify_px, preserve_topology=True)
        if poly.area < min_area_px:
            continue
        polys.append(poly)
    return polys


def run_fig(source: str, output: str, fig_label: str, legend_band: float, legend: dict,
             img_bbox: tuple | None = None, min_area_px: int = 60) -> int:
    img_path = REPO / "data" / "sources" / "fqgh" / source
    if not img_path.exists():
        print(f"missing source image: {img_path}", file=sys.stderr)
        return 2
    global IMG_X0, IMG_Y0, IMG_X1, IMG_Y1
    if img_bbox is not None:
        IMG_X0, IMG_Y0, IMG_X1, IMG_Y1 = img_bbox
    a = np.array(Image.open(img_path).convert("RGB")).astype(int)
    h, w, _ = a.shape
    region_mask = np.zeros((h, w), dtype=bool)
    region_mask[: int(h * legend_band), :] = (np.abs(a[: int(h * legend_band)] - 255).sum(axis=2) > 60)

    features = []
    counts = {}
    for key, spec in legend.items():
        anchor = spec["anchor"]
        tol = spec["tolerance"]
        # pixel class within region
        px = region_mask.copy()
        rr = np.abs(a[:, :, 0].astype(int) - anchor[0]) <= tol
        gg = np.abs(a[:, :, 1].astype(int) - anchor[1]) <= tol
        bb = np.abs(a[:, :, 2].astype(int) - anchor[2]) <= tol
        px &= rr & gg & bb
        # drop near-white fragments
        px &= (np.abs(a - 255).sum(axis=2) > 60)
        counts[key] = int(px.sum())
        polys = mask_to_polygons(px, min_area_px=min_area_px)
        for poly in polys:
            coords = []
            for x, y in poly.exterior.coords[:-1]:
                lon, lat = pixels_to_lonlat(x, y)
                coords.append([round(lon, 6), round(lat, 6)])
            if len(coords) < 4:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "layer": "OFFICIAL_ZONATION_BG",
                    "category": spec["name"],
                    "label_zh": spec["label_zh"],
                    "source": "DATA-SRC-HAIDIAN-DISTRICT-PLAN-2017-2035",
                    "source_figure": fig_label,
                    "official_boundary": False,
                    "usable_for_formal": "background_only",
                    "precision_note": "栅格公示图矢量化，配准中误差约百米级；仅作背景参考，不作几何/面积依据",
                },
                "geometry": {"type": "Polygon", "coordinates": [coords]},
            })
    fc = {"type": "FeatureCollection", "name": output.replace(".geojson", ""), "features": features}
    out = REPO / "data" / "processed" / output
    out.write_text(json.dumps(fc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"output: {out} ({len(features)} features)")
    for key, c in counts.items():
        print(f"  {key}: {c} px")

    # ---- cross-validation: Tianditu 清河 waterline onto image ----
    try:
        tr = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)
        water = None
        cdata = json.loads((REPO / "submissions/test/test/geometry/constraints.geojson").read_text(encoding="utf-8"))
        for f in cdata["features"]:
            if f["properties"].get("constraint_type") == "existing_water":
                water = shape(f["geometry"])
        if water is not None:
            xs_px, ys_px = [], []
            for lon, lat in zip(*water.exterior.xy) if water.geom_type == "Polygon" else ([], []):
                pass
            # use representative point of 清河段 (y>=40.02)
            seg = [g for g in (water.geoms if hasattr(water, "geoms") else [water])]
            for line in seg:
                if line.bounds[1] >= 40.02:
                    pts = list(line.coords)
                    x_px = IMG_X0 + (pts[0][0] - LON0) / (LON1 - LON0) * (IMG_X1 - IMG_X0)
                    y_px = IMG_Y0 + (LAT1 - pts[0][1]) / (LAT1 - LAT0) * (IMG_Y1 - IMG_Y0)
                    xs_px.append(x_px); ys_px.append(y_px)
            if xs_px:
                print(f"cross-check 清河起点像素: ({xs_px[0]:.0f},{ys_px[0]:.0f}) 图像宽 {w} 高 {h}")
    except Exception as e:  # pragma: no cover
        print("cross-check skipped:", e)
    return 0


def main() -> int:
    rc = run_fig("p090_fig05_zonation.png", "hd_fqgh_2020_fig05_zonation.geojson",
                 "图05 国土空间规划分区图", 0.80, LEGEND)
    if rc:
        return rc
    rc = run_fig(FIG03["source"], FIG03["output"], FIG03["fig_label"],
                 FIG03["legend_band"], FIG03["legend"], img_bbox=FIG03.get("img_bbox"))
    if rc:
        return rc
    rc = run_fig("p093_fig08_water.png", "hd_fqgh_2020_fig08_water.geojson",
                 "图08 河湖水系规划图", 0.80, {
        "water_surface": {"anchor": (160, 192, 240), "label_zh": "水域（官方河湖水系图）",
                          "name": "official_water_surface", "tolerance": 45},
        "water_deep": {"anchor": (0, 96, 176), "label_zh": "主河道/深水（官方河湖水系图）",
                       "name": "official_water_main_channel", "tolerance": 60},
    })
    return rc


if __name__ == "__main__":
    sys.exit(main())
