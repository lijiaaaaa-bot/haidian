#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""走廊交集 + 多源对照统计。

输入：
  - 3 个海淀子集 geocoded CSV（scripts/geocode_beijing_open_data.py 产物）
  - 高德 POI facility_poi_gaode.geojson（school/medical/charging）

输出：
  - data/processed/corridor_intersection_{kindergarten,health,charging}.csv
    （走廊内清单：原列 + lon/lat/source_row，含来源）
  - data/processed/corridor_intersection_summary.csv（每类 in/out/未编码 计数）
  - 多源对照表（开放平台走廊内数 vs 高德 POI 数 + 样例）stdout

一致性校验：走廊内 + 走廊外 == 编码成功数；编码成功 + 未编码 == 原子集总数。
交集以走廊 bbox 为准；未编码行以地址关键词辅助标注（corridor_kw_hint，
不替代坐标判断）。

用法：
  python3 scripts/corridor_intersection_and_comparison.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CORRIDOR_BBOX = {"lon_min": 116.310, "lon_max": 116.395, "lat_min": 39.935, "lat_max": 40.030}

# 走廊地名关键词（辅助标注，不替代坐标判断；沿用招拍挂 corridor 判定词表）
CORRIDOR_KEYWORDS = [
    "五塔寺", "明光村", "大钟寺", "知春路", "学院路", "西土城",
    "北下关", "双清路", "清华东路", "清河", "五道口", "西直门", "四道口",
]

DATASETS = {
    "kindergarten": {
        "name": "幼儿园名录",
        "geocoded": "data/sources/beijing-data-open/幼儿园名录_海淀区_geocoded.csv",
        "poi_category": "school",
        "label": "幼儿园",
    },
    "health": {
        "name": "社区卫生服务中心",
        "geocoded": "data/sources/beijing-data-open/社区卫生服务中心_海淀区_geocoded.csv",
        "poi_category": "medical",
        "label": "社区卫生",
    },
    "charging": {
        "name": "社会公用充电站",
        "geocoded": "data/sources/beijing-data-open/社会公用充电站_海淀区_geocoded.csv",
        "poi_category": "charging",
        "label": "充电站",
    },
}

POI_GEOJSON = "data/processed/facility_poi_gaode.geojson"


def in_corridor(lon, lat, bbox: dict | None = None) -> bool:
    bbox = bbox or CORRIDOR_BBOX
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    return (bbox["lon_min"] <= lon <= bbox["lon_max"]
            and bbox["lat_min"] <= lat <= bbox["lat_max"])


def classify_row(status: str, lon, lat, bbox: dict | None = None) -> str:
    """按编码状态与坐标分桶：in（走廊内）/ out（走廊外）/ not_geocoded。"""
    if status == "ok" and in_corridor(lon, lat, bbox):
        return "in"
    if status == "ok":
        return "out"
    return "not_geocoded"


def kw_hint(text: str) -> str:
    """地址关键词辅助标注（仅作提示，不替代坐标判断）。"""
    hits = [k for k in CORRIDOR_KEYWORDS if k in (text or "")]
    return "|".join(hits)


def load_geocoded(path: Path) -> list[dict]:
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    # 统一列名：未知原始列保持原样，补充 std 列
    for r in rows:
        r.setdefault("_lon", r.get("lon_wgs84", ""))
        r.setdefault("_lat", r.get("lat_wgs84", ""))
        r.setdefault("_status", r.get("geocode_status", ""))
        r.setdefault("_addr", next((r[k] for k in
                                    ("幼儿园地址", "地址", "区县具体地址", "geocode_query")
                                    if r.get(k)), ""))
    return rows


def load_poi_counts() -> dict:
    d = json.loads((ROOT / POI_GEOJSON).read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for f in d["features"]:
        cat = f["properties"].get("category", "")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def _point_name(r: dict) -> str:
    for k in ("幼儿园名称", "机构名称", "充电站点标准名称", "name"):
        if r.get(k):
            return r[k]
    return ""


def main():
    poi_counts = load_poi_counts()
    summary: list[dict] = []
    all_in_points: list[dict] = []
    print("=== 走廊交集（bbox 116.310-116.395, 39.935-40.030）===")
    for ds_key, ds in DATASETS.items():
        gc_path = ROOT / ds["geocoded"]
        if not gc_path.exists():
            print("跳过 %s：geocoded 文件未生成（%s）" % (ds["name"], ds["geocoded"]))
            continue
        rows = load_geocoded(gc_path)
        buckets = {"in": [], "out": [], "not_geocoded": []}
        for r in rows:
            b = classify_row(r["_status"], r["_lon"], r["_lat"])
            buckets[b].append(r)

        # 一致性校验
        n_ok = len(buckets["in"]) + len(buckets["out"])
        n_geocoded = sum(1 for r in rows if r["_status"] == "ok")
        n_total = len(rows)
        n_not = n_total - n_geocoded
        assert n_ok == n_geocoded, "%s: in+out(%d) != ok(%d)" % (ds_key, n_ok, n_geocoded)
        assert len(buckets["not_geocoded"]) == n_not, "%s: not_geocoded 桶不一致" % ds_key
        print("%s：总 %d ｜ 走廊内 %d ｜ 走廊外 %d ｜ 未编码 %d（校验 in+out=%d ✓）"
              % (ds["name"], n_total, len(buckets["in"]), len(buckets["out"]), n_not, n_ok))

        # 走廊内清单落盘（含来源与坐标）
        out_csv = ROOT / ("data/processed/corridor_intersection_%s.csv" % ds_key)
        cols = list(rows[0].keys()) if rows else []
        std = ["source_row", "lon_wgs84", "lat_wgs84", "geocode_status"]
        with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols + ["corridor_kw_hint"])
            w.writeheader()
            for r in buckets["in"]:
                hint = kw_hint(r.get("_addr", "")) if r["_status"] != "ok" else ""
                out = dict(r)
                out["corridor_kw_hint"] = hint
                w.writerow(out)
        print("  走廊内清单 → %s（%d 行）" % (out_csv, len(buckets["in"])))

        # 未编码行的关键词辅助标注计数
        kw_hits = sum(1 for r in buckets["not_geocoded"] if kw_hint(r["_addr"]))
        print("  未编码 %d 行中地址含走廊关键词 %d 行（辅助标注，非坐标结论）"
              % (len(buckets["not_geocoded"]), kw_hits))

        summary.append({
            "category": ds_key, "label": ds["label"],
            "total": n_total, "corridor_in": len(buckets["in"]),
            "corridor_out": len(buckets["out"]), "not_geocoded": n_not,
            "geocoded_ok": n_geocoded, "poi_gaode": poi_counts.get(ds["poi_category"], 0),
        })
        # 汇总走廊内点位（供 geojson）
        for r in buckets["in"]:
            all_in_points.append({
                "category": ds_key, "label": ds["label"], "name": _point_name(r),
                "addr": r.get("_addr", ""), "lon": r["_lon"], "lat": r["_lat"],
                "source_row": r.get("source_row", ""),
            })

    # 走廊内点位 geojson（合并三类）
    gj = {
        "type": "FeatureCollection",
        "name": "corridor_intersection_points_open_data",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "metadata": {
            "title": "北京开放平台海淀子集走廊内点位（地理编码后）",
            "generated_at": "2026-08-18",
            "source": "北京市公共数据开放平台 3 数据集 + 高德地理编码（GCJ-02→WGS84）",
            "authority": "official 名录经地理编码定位；坐标为编码结果，精度受地址文本与编码质量影响",
        },
        "features": [
            {
                "type": "Feature",
                "properties": {"category": p["category"], "label": p["label"],
                               "name": p["name"], "address": p["addr"],
                               "source_row": p["source_row"]},
                "geometry": {"type": "Point", "coordinates": [float(p["lon"]), float(p["lat"])]},
            }
            for p in all_in_points
        ],
    }
    gj_path = ROOT / "data/processed/corridor_intersection_points_open_data.geojson"
    gj_path.write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
    print("\n走廊内点位 geojson → %s（%d 个点）" % (gj_path, len(all_in_points)))

    # 汇总落盘
    sum_csv = ROOT / "data/processed/corridor_intersection_summary.csv"
    with open(sum_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    # 多源对照
    print("\n=== 多源对照：开放平台走廊内 vs 高德 POI ===")
    print("%-6s %-8s %-10s %-10s %-10s" % ("类别", "开放平台走廊内", "高德POI", "开放平台全海淀", "未编码"))
    for s in summary:
        print("%-6s %-8d %-10d %-10d %-10d" % (
            s["label"], s["corridor_in"], s["poi_gaode"], s["total"], s["not_geocoded"]))
    print("\n对照说明：开放平台=机构/站点名录（含地址字段），高德 POI=点位库（含商铺/诊所等更广分类）；")
    print("两源口径不同，数量不可直接相减，仅作底数互证。")
    print("汇总 → %s" % sum_csv)


if __name__ == "__main__":
    main()
