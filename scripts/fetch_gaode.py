#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高德 Web 服务数据采集：京张走廊设施 POI + 海淀区行政边界（background_reference）。

映射：
  - /v3/place/polygon（走廊 bbox 内按分类分页）→ data/processed/facility_poi_gaode.geojson
    → GAP-SERVICE-001 部分缓解（学校/医疗/商超/充电站底数）
  - /v3/config/district（keywords=海淀区, extensions=all）→ data/processed/haidian_district_gaode.geojson
    → GAP-BOUNDARY-001/002 背景参考（非 official 边界）

合规（沿用 docs/map-api-assessment-2026-08-14.md §⑥）：
  - 输出 authority=background_reference，绝不替代 official 边界/控规指标；
  - 高德坐标 GCJ-02 → 本文件统一输出 WGS84（EPSG:4326），近似逆变换误差数米；
  - 成果署名 © 高德地图；限速 ≥1s/请求 + 失败退避；免费 key 有日配额/QPS 限制；
  - 不商用（本项目为竞赛/研究用途）。

Key 配置（不提交 git）：
  环境变量 AMAP_KEY / AMAP_JCODE，或 data/config/gaode_keys.local.json：
  {"key": "...", "jscode": "..."}
  高德 Web 服务 key（2021-12 后个人 key）请求需同时带 key 与 jscode（安全密钥）。

用法：
  python3 scripts/fetch_gaode.py --poi          # 走廊设施 POI
  python3 scripts/fetch_gaode.py --district     # 海淀区行政边界
  python3 scripts/fetch_gaode.py                # 两者都跑
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "haidian-jingzhang-ai-belt-research/1.0 (城市设计研究用途)"
BASE = "https://restapi.amap.com/v3"

# 走廊 bbox（统筹研究范围外扩）：39.935–40.030, 116.310–116.395（沿用地图 API 评估文档）
CORRIDOR_BBOX = "116.310,39.935;116.395,40.030"

# 高德 POI 分类码（一级/二级，分类码表以官方为准，接入时核对）。
# 注：school 不走 polygon 分类码——/v3/place/polygon types=190000 实测返回
# 大量"地名地址信息"（立交桥/道路名）垃圾；改用 /v3/place/text types=中文类名。
POI_CATEGORIES = {
    "medical":  {"types": "090000", "name_zh": "医疗（医疗保健服务）"},
    "shopping": {"types": "060000", "name_zh": "商超（购物服务）"},
    "charging": {"types": "011100", "name_zh": "充电站（汽车服务）"},
}

# 学校类名（科教文化服务;学校;{高等院校/中学/小学/幼儿园/职业技术学校}）
SCHOOL_TYPE_NAMES = ["学校", "小学", "幼儿园", "职业技术学校"]


def load_keys() -> dict:
    key = os.environ.get("AMAP_KEY", "")
    jscode = os.environ.get("AMAP_JCODE", "")
    if not key:
        cfg = ROOT / "data/config/gaode_keys.local.json"
        if cfg.exists():
            d = json.loads(cfg.read_text(encoding="utf-8"))
            key = d.get("key", "")
            jscode = d.get("jscode", "")
    if not key:
        sys.exit("未配置高德 key：设置环境变量 AMAP_KEY/AMAP_JCODE 或 data/config/gaode_keys.local.json")
    return {"key": key, "jscode": jscode}


def http_get_json(url: str, params: dict, keys: dict, retries: int = 3) -> dict:
    params = dict(params)
    params["key"] = keys["key"]
    if keys.get("jscode"):
        params["jscode"] = keys["jscode"]
    qs = "&".join("%s=%s" % (k, v) for k, v in params.items())
    full = "%s?%s" % (url, qs)
    for attempt in range(retries):
        out = subprocess.run(
            ["curl", "-s", "--max-time", "30", "-A", USER_AGENT, full],
            capture_output=True)
        try:
            d = json.loads(out.stdout)
        except ValueError:
            time.sleep(2 * (attempt + 1))
            continue
        if d.get("status") != "1":
            info = d.get("info", "")
            # 配额类错误退避重试，其余直接报错
            if attempt < retries - 1 and any(k in info for k in ("DAILY_QUERY_OVER_LIMIT", "BUSY")):
                time.sleep(5 * (attempt + 1))
                continue
            sys.exit("高德 API 错误: %s (%s)" % (info, d.get("infocode", "")))
        return d
    sys.exit("高德 API 请求失败（多次重试）")


# ── GCJ-02 → WGS84 近似逆变换（标准算法，误差数米）──
def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lon - dlon, lat - dlat


# ── 输出结构（沿用项目 geojson 约定）──
def make_collection(name: str, attribution: str, purpose: str, features: list) -> dict:
    return {
        "type": "FeatureCollection",
        "name": name,
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "metadata": {
            "title": name,
            "generated_at": "2026-08-14",
            "source": "高德开放平台 Web 服务（restapi.amap.com）",
            "license_attribution": attribution,
            "crs_note": "高德原始坐标为 GCJ-02，已近似逆变换为 WGS84（误差数米）；background_reference，非 official",
            "purpose": purpose,
            "authority": "background_reference（公开商业地图背景参考，不构成 official 红线）",
        },
        "features": features,
    }


def fetch_district(keys: dict) -> dict:
    d = http_get_json(BASE + "/config/district",
                      {"keywords": "海淀区", "subdistrict": "0", "extensions": "all"}, keys)
    districts = d.get("districts") or []
    if not districts:
        sys.exit("district 查询无结果")
    dist = districts[0]
    print("海淀区 adcode=%s 级别=%s 中心=%s" % (dist.get("adcode"), dist.get("level"), dist.get("center")))
    polys: list = []
    polyline = dist.get("polyline") or ""
    for chunk in polyline.split("|"):
        if not chunk.strip():
            continue
        ring = []
        for pt in chunk.split(";"):
            lon_s, lat_s = pt.split(",")
            ring.append(list(gcj02_to_wgs84(float(lon_s), float(lat_s))))
        if len(ring) >= 4:
            ring.append(ring[0][:])  # 闭合
            polys.append([ring])
    if not polys:
        sys.exit("district polyline 解析为空")
    geom = {"type": "Polygon" if len(polys) == 1 else "MultiPolygon", "coordinates": polys}
    feat = {
        "type": "Feature",
        "properties": {
            "layer": "GAODE_DISTRICT_BOUNDARY",
            "name": "海淀区",
            "adcode": dist.get("adcode", ""),
            "source": "DATA-SRC-GAODE-DISTRICT-BOUNDARY-20260814",
            "official_boundary": False,
            "usable_for_formal": "background_only",
            "crs_source": "GCJ-02→WGS84 近似转换（误差数米）",
            "precision_note": "高德行政区划轮廓为背景参考，非官方红线；边界精度数米级，实际以规自委 official 为准",
        },
        "geometry": geom,
    }
    coll = make_collection(
        "haidian_district_gaode",
        "数据 © 高德地图（高德开放平台 Web 服务），background_reference",
        "海淀区行政边界背景参考，与锚点/文字四至对照（GAP-BOUNDARY-001/002 背景）",
        [feat])
    out = ROOT / "data/processed/haidian_district_gaode.geojson"
    out.write_text(json.dumps(coll, ensure_ascii=False), encoding="utf-8")
    print("海淀区边界 polygon 数=%d → %s" % (len(polys), out))
    return coll


def fetch_school_poi_text(keys: dict, features: list, seen: set) -> int:
    """学校：/v3/place/text types=中文类名（学校/小学/幼儿园/职业技术学校）分页 →
    bbox 过滤 + 类型串过滤（须含"学校"）。

    /v3/place/polygon types=190000 在走廊 bbox 内实测返回大量"地名地址信息"
    （立交桥/道路名），故学校类不用 polygon；/v3/place/text 的 types 参数支持
    中文类名。city=海淀区：走廊 bbox 完全位于海淀区内，区级查询可绕开北京市
    600 条相关性排序上限（中学等小类在北京市查询中被稀释，实测仅 7 条进走廊）。
    """
    added = 0
    for tname in SCHOOL_TYPE_NAMES:
        page = 1
        while page <= 40:
            d = http_get_json(BASE + "/place/text",
                              {"city": "海淀区", "types": tname, "offset": "25", "page": str(page)}, keys)
            pois = d.get("pois") or []
            if not pois:
                break
            for p in pois:
                ptype = p.get("type", "")
                if "学校" not in ptype:  # 类型串过滤（排除地名/机构培训等）
                    continue
                poiid = p.get("id", "")
                if poiid in seen:
                    continue
                loc = p.get("location", "")
                if not loc:
                    continue
                lon, lat = gcj02_to_wgs84(*[float(x) for x in loc.split(",")])
                if not (116.310 <= lon <= 116.395 and 39.935 <= lat <= 40.030):
                    continue
                seen.add(poiid)
                features.append({
                    "type": "Feature",
                    "properties": {
                        "layer": "GAODE_FACILITY_POI",
                        "gaode_poiid": poiid,
                        "name": p.get("name", ""),
                        "type": ptype,
                        "address": p.get("address", ""),
                        "category": "school",
                        "source": "DATA-SRC-GAODE-FACILITY-POI-20260815",
                        "official_boundary": False,
                        "usable_for_formal": "background_only",
                        "crs_source": "GCJ-02→WGS84 近似转换（误差数米）",
                        "precision_note": "高德 POI 点位为背景参考，位置精度数米级；覆盖不代表完整，缺漏不代表不存在",
                    },
                    "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                })
                added += 1
            if len(pois) < 25:
                break
            page += 1
            time.sleep(1.0)
    return added


def fetch_poi(keys: dict) -> dict:
    features: list = []
    seen: set = set()
    for cat, spec in POI_CATEGORIES.items():
        page = 1
        total = 0
        while page <= 20:
            d = http_get_json(BASE + "/place/polygon",
                              {"polygon": CORRIDOR_BBOX, "types": spec["types"],
                               "offset": "25", "page": str(page)}, keys)
            pois = d.get("pois") or []
            if not pois:
                break
            for p in pois:
                poiid = p.get("id", "")
                if poiid in seen:
                    continue
                seen.add(poiid)
                loc = p.get("location", "")
                if not loc:
                    continue
                lon, lat = gcj02_to_wgs84(*[float(x) for x in loc.split(",")])
                features.append({
                    "type": "Feature",
                    "properties": {
                        "layer": "GAODE_FACILITY_POI",
                        "gaode_poiid": poiid,
                        "name": p.get("name", ""),
                        "type": p.get("type", ""),
                        "address": p.get("address", ""),
                        "category": cat,
                        "source": "DATA-SRC-GAODE-FACILITY-POI-20260814",
                        "official_boundary": False,
                        "usable_for_formal": "background_only",
                        "crs_source": "GCJ-02→WGS84 近似转换（误差数米）",
                        "precision_note": "高德 POI 点位为背景参考，位置精度数米级；覆盖不代表完整，缺漏不代表不存在",
                    },
                    "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                })
            total += len(pois)
            print("  %s: page %d → 累计 %d" % (cat, page, len(features)))
            if len(pois) < 25:
                break
            page += 1
            time.sleep(1.0)
        time.sleep(1.0)
        print("%s（%s）：POI %d 个" % (spec["name_zh"], cat, sum(1 for f in features if f["properties"]["category"] == cat)))

    # 学校补充：types=学校 文本搜索 + bbox 过滤（polygon 按 190000 仅 36 个，偏少）
    n_school = fetch_school_poi_text(keys, features, seen)
    print("school（types=学校 文本搜索 + bbox 过滤）：补充 %d 个，合计 %d 个" % (
        n_school, sum(1 for f in features if f["properties"]["category"] == "school")))
    coll = make_collection(
        "facility_poi_gaode",
        "数据 © 高德地图（高德开放平台 Web 服务），background_reference",
        "京张走廊设施 POI 底数（学校/医疗/商超/充电站）→ GAP-SERVICE-001 部分缓解",
        features)
    out = ROOT / "data/processed/facility_poi_gaode.geojson"
    out.write_text(json.dumps(coll, ensure_ascii=False), encoding="utf-8")
    print("POI 总计 %d 个（去重后）→ %s" % (len(features), out))
    return coll


def main():
    import argparse
    ap = argparse.ArgumentParser(description="高德 Web 服务数据采集（background_reference）")
    ap.add_argument("--poi", action="store_true", help="走廊设施 POI")
    ap.add_argument("--district", action="store_true", help="海淀区行政边界")
    args = ap.parse_args()
    keys = load_keys()
    if not args.poi and not args.district:
        args.poi = args.district = True
    if args.district:
        fetch_district(keys)
    if args.poi:
        fetch_poi(keys)
    print("done")


if __name__ == "__main__":
    main()
