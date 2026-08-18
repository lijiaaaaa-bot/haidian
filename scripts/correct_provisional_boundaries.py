#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按真实锚点平移修正 provisional 重点片区多边形（保留 provisional 纪律）。

背景（2026-08-14，见 docs/map-api-assessment-2026-08-14.md §3 与
data/processed/anchors_geocoded.geojson）：
  Nominatim/Overpass 实测锚点显示两处重点片区 provisional polygon 与真实
  地名锚点存在 0.7–1.8km 级偏移：
    - PROV-KEY-002（北京AI原点社区）：多边形整体偏东约 1km，五道口站
      （116.33170, 39.99148）落在多边形外 895m → 西移 Δlon = -0.0110°
    - PROV-KEY-003（大钟寺AI产业聚集区）：多边形整体偏南约 1.8km，大钟寺
      本体/古钟博物馆（116.33199, 39.96783）在旧多边形北侧 1.8km →
      北移 Δlat = +0.0209°、西移 Δlon = -0.0101°（平移后大钟寺本体落于
      多边形纬度居中、经度近西界内，与其命名锚点对齐）

修正方式：整体平移（刚性），形状与面积不变；仍为 provisional 推测边界，
绝不升格为 official。修正后残留差异（大钟寺本体经度仍在多边形西侧约 1km、
明光村仍位于多边形以南、PROV-KEY-002 西移后超出 SITE 多边形西界约 0.009°）
如实记录于 data/processed/provisional-boundary-anchor-correction-notes.md，
等待依申请公开 official 矢量替换。

同步更新三份文件（同一几何源的三份拷贝）：
  1. brief/site-package/geometry/provisional_boundaries.geojson（源）
  2. brief/site-package/geometry/provisional_boundaries_upgraded.geojson
  3. submissions/test/key_areas_boundary.geojson
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 平移量（度，WGS84/EPSG:4326）：刚性平移保持形状与面积
SHIFTS = {
    "PROV-KEY-002": {"lon": -0.0110, "lat": 0.0},
    "PROV-KEY-003": {"lon": -0.0101, "lat": 0.0209},
}

# 平移依据（锚点 → 偏移量，来源 anchors_geocoded.geojson）
CORRECTION_BASIS = {
    "PROV-KEY-002": {
        "anchor": "五道口（railway/station，116.33170, 39.99148）",
        "reported_offset": "多边形偏东约 1km；五道口站距旧多边形 895m",
        "shift_deg": "lon -0.0110",
        "residual_notes": "西移后多边形西界约 116.331，五道口站约 60m 入界；多边形东界 116.342 仍在学院路（≈116.347）以西；多边形超出 SITE（总体设计范围）西界约 0.009°（SITE 西界本身为文字四至粗略边界，待 official 矢量替换）",
    },
    "PROV-KEY-003": {
        "anchor": "大钟寺/古钟博物馆（amenity/place_of_worship，116.33199, 39.96783）",
        "reported_offset": "多边形南移约 1.8km（旧多边形 lat 39.944–39.94984，大钟寺本体 ≈39.968）",
        "shift_deg": "lat +0.0209, lon -0.0101",
        "residual_notes": "平移后大钟寺本体落于多边形纬度居中、经度近西界内；明光村（39.9566, 116.3460）仍在多边形以南（纬度界外）；多边形西移后西界约 116.3319，与 SITE（总体设计范围）西界（约 116.340）重叠区外溢约 0.008°——SITE 西界本身为文字四至粗略边界，待 official 矢量替换",
    },
}


def _deg_per_m(lat: float) -> float:
    return 1.0 / (111320.0 * math.cos(math.radians(lat)))


def translate_geom(geom: dict, dlon: float, dlat: float) -> dict:
    def tx(coord):
        return [coord[0] + dlon, coord[1] + dlat]

    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [
            [tx(c) for c in ring] for ring in geom["coordinates"]]}
    if geom["type"] == "MultiPolygon":
        return {"type": "MultiPolygon", "coordinates": [
            [[tx(c) for c in ring] for ring in poly] for poly in geom["coordinates"]]}
    raise ValueError("unsupported geometry type: %s" % geom["type"])


def polygon_area_sqm(geom: dict) -> float:
    """球面近似面积（m²），用于平移前后核对（平移应保持面积不变）。"""
    R = 6371000.0

    def ring_area(ring):
        area = 0.0
        for i in range(len(ring) - 1):
            lon1, lat1 = math.radians(ring[i][0]), math.radians(ring[i][1])
            lon2, lat2 = math.radians(ring[i + 1][0]), math.radians(ring[i + 1][1])
            area += (lon2 - lon1) * (2.0 + math.sin(lat1) + math.sin(lat2))
        return area * R * R / 2.0

    if geom["type"] == "Polygon":
        return abs(ring_area(geom["coordinates"][0]))
    if geom["type"] == "MultiPolygon":
        return sum(abs(ring_area(p[0])) for p in geom["coordinates"])
    return 0.0


def apply_corrections(features: list[dict], verify_area: bool = True, revert: bool = False) -> dict:
    """对命中 id 的 feature 执行平移并写修正元数据。返回 {id: (area_before, area_after)}。

    PROV-KEY-SCOPE-001 为三区汇总 multipolygon，其子多边形与 PROV-KEY-00X
    的旧坐标逐点相同 —— 按坐标匹配逐子多边形平移，保持汇总与分区一致。
    幂等：已带 anchor_corrected 元数据的 feature 直接跳过；--revert 时回退。
    """
    areas = {}
    # 预构建：KEY 多边形 id → 旧环坐标（用于 SCOPE 子多边形匹配）
    pre_rings = {}
    for feat in features:
        fid = feat.get("id", "")
        corrected = feat.get("properties", {}).get("anchor_corrected")
        if fid in SHIFTS and feat.get("geometry") and (revert or not corrected):
            pre_rings[fid] = feat["geometry"]["coordinates"]

    def rings_equal(a, b, eps=1e-9):
        if len(a) != len(b):
            return False
        return all(
            len(ra) == len(rb)
            and all(abs(x - y) <= eps for x, y in zip(pa, pb))
            for ra, rb in zip(a, b) for pa, pb in zip(ra, rb)
        )

    for feat in features:
        fid = feat.get("id", "")
        geom = feat.get("geometry")
        if geom is None:
            continue
        props = feat.setdefault("properties", {})
        if fid in SHIFTS:
            if props.get("anchor_corrected") and not revert:
                continue  # 幂等：已修正不再重复平移
            shift = SHIFTS[fid]
            sign = -1.0 if revert else 1.0
            area_before = polygon_area_sqm(geom)
            feat["geometry"] = translate_geom(geom, sign * shift["lon"], sign * shift["lat"])
            area_after = polygon_area_sqm(feat["geometry"])
            if verify_area and abs(area_after - area_before) / max(area_before, 1e-9) > 1e-3:
                raise ValueError("%s 平移后面积变化 %.4f%%" % (
                    fid, 100 * (area_after - area_before) / area_before))
            areas[fid] = (area_before, area_after)

            if revert:
                props.pop("anchor_corrected", None)
                props.pop("anchor_correction", None)
            else:
                basis = CORRECTION_BASIS[fid]
                props["anchor_corrected"] = True
                props["anchor_correction"] = {
                    "date": "2026-08-14",
                    "basis": basis["anchor"],
                    "reported_offset": basis["reported_offset"],
                    "shift_deg": basis["shift_deg"],
                    "residual_notes": basis["residual_notes"],
                    "method": "rigid translation preserving shape and area",
                    "source": "data/processed/anchors_geocoded.geojson（© OpenStreetMap contributors, ODbL 1.0）",
                    "still_provisional": True,
                }
                props["area_sqm_calculated"] = round(area_after, 3)
        elif fid == "PROV-KEY-SCOPE-001" and geom["type"] == "MultiPolygon":
            if props.get("anchor_corrected") and not revert:
                continue
            # 汇总 multipolygon：按子多边形旧坐标匹配 002/003 并各自平移
            shifted_parts = []
            for poly in geom["coordinates"]:
                matched = next((k for k, r in pre_rings.items() if rings_equal(r, poly)), None)
                if matched:
                    s = SHIFTS[matched]
                    sign = -1.0 if revert else 1.0
                    shifted_parts.append(translate_geom(
                        {"type": "Polygon", "coordinates": poly},
                        sign * s["lon"], sign * s["lat"])["coordinates"])
                else:
                    shifted_parts.append(poly)
            geom["coordinates"] = shifted_parts
            if revert:
                props.pop("anchor_corrected", None)
                props.pop("anchor_correction_note", None)
            else:
                props["anchor_corrected"] = True
                props["anchor_correction_note"] = (
                    "汇总 multipolygon 子多边形随 PROV-KEY-002/003 同步平移（2026-08-14 锚点修正）")
    return areas


def main():
    import argparse
    ap = argparse.ArgumentParser(description="按真实锚点平移修正 provisional 重点片区多边形")
    ap.add_argument("--revert", action="store_true", help="回退上一次锚点修正（幂等）")
    args = ap.parse_args()

    targets = [
        ROOT / "brief/site-package/geometry/provisional_boundaries.geojson",
        ROOT / "brief/site-package/geometry/provisional_boundaries_upgraded.geojson",
        ROOT / "submissions/test/key_areas_boundary.geojson",
    ]
    all_areas = {}
    for path in targets:
        if not path.exists():
            print("跳过（不存在）：%s" % path)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        areas = apply_corrections(data["features"], revert=args.revert)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("已更新 %s" % path)
        for fid, (before, after) in areas.items():
            print("  %s  面积 %.0f → %.0f m²（变化 %.4f%%）" % (
                fid, before, after, 100 * (after - before) / before))
        all_areas.update(areas)

    if args.revert:
        print("已回退。")
        return

    # 校验输出：锚点落位（射线法 point-in-polygon）
    data = json.loads((targets[0]).read_text(encoding="utf-8"))
    by_id = {f["id"]: f for f in data["features"]}
    anchors = {
        "PROV-KEY-002": ("五道口", (116.3317017, 39.9914779)),
        "PROV-KEY-003": ("大钟寺", (116.3319879, 39.9678257)),
    }

    def contains(geom, lon, lat):
        def ring_hit(ring):
            inside = False
            n = len(ring) - 1
            x, y = lon, lat
            for i in range(n):
                x1, y1 = ring[i][0], ring[i][1]
                x2, y2 = ring[i + 1][0], ring[i + 1][1]
                if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
                    inside = not inside
            return inside

        if geom["type"] == "Polygon":
            return ring_hit(geom["coordinates"][0])
        if geom["type"] == "MultiPolygon":
            return any(ring_hit(p[0]) for p in geom["coordinates"])
        return False

    for fid, (name, pt) in anchors.items():
        geom = by_id[fid]["geometry"]
        ok = contains(geom, *pt)
        dist = "（需计算）"
        print("锚点校验 %s（%s）in %s：%s" % (name, pt, fid, "✅ 在多边形内" if ok else "❌ 不在多边形内"))
        if not ok:
            sys.exit("锚点校验失败：%s 未落入 %s" % (name, fid))
    print("done")


if __name__ == "__main__":
    main()
