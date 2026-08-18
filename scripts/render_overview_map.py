#!/usr/bin/env python3
"""Render the overview base map for the 京张走廊 AI 创新带 submission.

Base layers (real, registered data):
  - roads / railways / water / boundaries: 天地图 WFS 1:100万 public data
    (data/processed/tianditu_wfs_beijing.geojson, source DATA-SRC-TIANDITU-WFS-1M)
  - overlay: provisional site boundary (dashed) + key areas from the submission

Usage:
    python3 scripts/render_overview_map.py [-o out.png]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import font_manager
from matplotlib.patches import Polygon as MplPoly
from shapely.geometry import shape, box

REPO = Path(__file__).resolve().parents[1]
CJK_FONT = "/System/Library/Fonts/Supplemental/Songti.ttc"

X0, X1, Y0, Y1 = 116.315, 116.375, 39.925, 40.045
MID_LAT = (Y0 + Y1) / 2.0
COS_MID = __import__("math").cos(__import__("math").radians(MID_LAT))

SUB = REPO / "submissions" / "test" / "test"
BASE = REPO / "data" / "processed" / "tianditu_wfs_beijing.geojson"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--out", default=str(REPO / "docs" / "overview-map.png"))
    args = parser.parse_args()

    try:
        font_manager.fontManager.addfont(CJK_FONT)
        cjk = "Songti SC"
    except Exception:
        cjk = "DejaVu Sans"
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = cjk
    plt.rcParams["axes.unicode_minus"] = False

    base = json.loads(BASE.read_text(encoding="utf-8"))
    clipbox = box(X0, Y0, X1, Y1)

    def clip(layer: str):
        return [(f, shape(f["geometry"])) for f in base["features"]
                if f["properties"].get("tdt_layer") == layer
                and shape(f["geometry"]).intersects(clipbox)]

    roads, rails, waters, bou = clip("LRDL"), clip("LRRL"), clip("HYDL"), clip("BOUL")

    fig, ax = plt.subplots(figsize=(16, 10), dpi=150)
    ax.set_xlim(X0, X1)
    ax.set_ylim(Y0, Y1)
    ax.set_aspect(1.0 / COS_MID)

    def draw_line(g, color, lw, z, ls="-"):
        if g.geom_type == "LineString":
            xs, ys = g.xy
            ax.plot(xs, ys, color=color, lw=lw, zorder=z, linestyle=ls, solid_capstyle="round")
        elif g.geom_type == "MultiLineString":
            for line in g.geoms:
                xs, ys = line.xy
                ax.plot(xs, ys, color=color, lw=lw, zorder=z, linestyle=ls, solid_capstyle="round")

    # OSM 现状路网（浅灰细线背景，非红线；DATA-SRC-OSM, ODbL）
    osm_path = REPO / "data" / "processed" / "osm_road_network.geojson"
    if osm_path.exists():
        osm = json.loads(osm_path.read_text(encoding="utf-8"))
        osm_lw = {"expressway": 0.7, "primary": 0.6, "secondary": 0.55,
                  "tertiary": 0.45, "residential": 0.35, "service": 0.25,
                  "footway": 0.2, "pedestrian": 0.2}
        for f in osm["features"]:
            cls = f["properties"].get("road_class", "residential")
            draw_line(shape(f["geometry"]), "#9aa0a6", osm_lw.get(cls, 0.3), 2)

    # 境界（淡灰）
    for f, g in bou:
        draw_line(g, "#cccccc", 0.8, 1)
    # 水系（蓝）
    for f, g in waters:
        draw_line(g, "#2f6fe4", 2.2, 3)
        name = f["properties"].get("NAME", "")
        if name and g.geom_type == "LineString":
            pt = g.interpolate(0.5)
            ax.annotate(name, (pt.x, pt.y), fontsize=10, color="#1d4fae", ha="center",
                        va="center", fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75),
                        zorder=4)
    # 铁路（深棕虚线）
    for f, g in rails:
        draw_line(g, "#5b3a1e", 2.4, 5, ls=(0, (6, 2)))
        name = f["properties"].get("NAME", "")
        if ("京包" in name or "十三" in name) and g.geom_type == "LineString":
            pt = g.interpolate(0.5)
            ax.annotate(f"{name}（京张铁路）", (pt.x, pt.y), fontsize=10, color="#5b3a1e",
                        ha="center", va="center", fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8),
                        zorder=6)
    # 道路（灰，高速深）
    highway = ["高速", "拉萨", "G6", "京藏", "五环", "三环", "德胜门", "西直门"]
    for f, g in roads:
        name = f.get("properties", {}).get("NAME", "")
        is_hw = any(k in name for k in highway)
        draw_line(g, "#555555" if is_hw else "#999999", 2.0 if is_hw else 1.0, 2)
        if is_hw and name and g.geom_type == "LineString":
            pt = g.interpolate(0.5)
            ax.annotate(name, (pt.x, pt.y), fontsize=9, color="#333333", ha="center", va="center",
                        bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="#bbbbbb", alpha=0.8),
                        zorder=4)

    # overlay: provisional 边界（虚线、淡色、水印）
    sub = json.loads((SUB / "geometry" / "site_boundary.geojson").read_text(encoding="utf-8"))
    for f in sub["features"]:
        g = shape(f["geometry"])
        xs, ys = g.exterior.xy
        ax.plot(xs, ys, color="#e94560", lw=2.0, zorder=7, linestyle=(0, (5, 4)),
                label="总体设计范围（provisional）")
    ka = json.loads((SUB / "geometry" / "key_areas.geojson").read_text(encoding="utf-8"))
    ka_colors = ["#e94560", "#f2a93b", "#2f9e44"]
    ka_names = ["众智园AI自主创新加速区", "北京AI原点社区", "大钟寺AI产业聚集区"]
    for i, f in enumerate(ka["features"]):
        g = shape(f["geometry"])
        ax.add_patch(MplPoly(list(g.exterior.coords), closed=True,
                             facecolor=ka_colors[i % 3], edgecolor="white", alpha=0.35,
                             lw=1.2, zorder=6))
        cx, cy = g.centroid.x, g.centroid.y
        ax.annotate(ka_names[i % 3], (cx, cy), fontsize=11, color="#1a1a2e", ha="center",
                    va="center", fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=ka_colors[i % 3], alpha=0.9),
                    zorder=8)

    # 水印
    ax.text((X0 + X1) / 2, (Y0 + Y1) / 2, "PROVISIONAL", fontsize=46, color="#e945600f",
            ha="center", va="center", fontweight="bold", zorder=9)

    # 指北针
    ax.annotate("N", xy=(X1 - 0.0012, Y1 - 0.0012), fontsize=16, fontweight="bold",
                color="#1a1a2e", ha="center", va="center")
    ax.annotate("", xy=(X1 - 0.0012, Y1 - 0.0022), xytext=(X1 - 0.0012, Y1 - 0.0002),
                arrowprops=dict(arrowstyle="-|>", color="#e94560", lw=2.5))

    # 比例尺（2 km，cos 修正）
    km_per_deg_lon = 111.0 * COS_MID
    scale_deg = 2.0 / km_per_deg_lon
    sx0, sy0 = X0 + 0.004, Y0 + 0.0022
    ax.plot([sx0, sx0 + scale_deg], [sy0, sy0], color="#1a1a2e", lw=3)
    ax.plot([sx0, sx0], [sy0 - 0.0006, sy0 + 0.0006], color="#1a1a2e", lw=2)
    ax.plot([sx0 + scale_deg, sx0 + scale_deg], [sy0 - 0.0006, sy0 + 0.0006], color="#1a1a2e", lw=2)
    ax.text(sx0 + scale_deg / 2, sy0 - 0.0014, "2 km", fontsize=10, ha="center", color="#1a1a2e")

    # 图例与标题
    ax.legend(loc="upper left", fontsize=11, framealpha=0.92)
    ax.set_title("京张走廊 AI 创新带 · 总体设计范围（底图：天地图 1:100万公众版，官方登记）",
                 fontsize=15, fontweight="bold", pad=12)
    ax.set_xlabel("经度（EPSG:4326；底图位置中误差约 100–500m，仅示意；来源 DATA-SRC-TIANDITU-WFS-1M）")
    ax.grid(True, linestyle=":", alpha=0.3)

    plt.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=150)
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
