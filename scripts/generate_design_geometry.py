#!/usr/bin/env python3
"""Generate design-grade provisional geometry for the 京张走廊 AI 创新带 submission.

Replaces placeholder bbox geometry with the design-expert plans (recorded in
intent-lab artifact_298847c1a3b7455b):
  - land_use.geojson: 19 parcels (8 overall + 11 key-area sub-zones)
  - buildings.geojson: 16 building blocks
  - green_space.geojson: 5 green spaces (buffered from real water/rail lines)
  - public_space.geojson: 5 public spaces
  - phasing.geojson: 3 phases

All output is provisional (official_boundary=false, pending regulatory
confirmation). Run from repo root; needs PYTHONPATH with shapely/pyproj.

Usage:
    PYTHONPATH=/tmp/haidian-deps python3 scripts/generate_design_geometry.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import MultiLineString, MultiPolygon, Polygon, shape
from shapely import make_valid
from shapely.ops import transform, unary_union
from pyproj import Transformer

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SUBMISSION = REPO / "submissions" / "test" / "test"
GEO: Path = DEFAULT_SUBMISSION / "geometry"

TR = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)
TR_INV = Transformer.from_crs("EPSG:4548", "EPSG:4326", always_xy=True)


def to4548(g):
    return transform(TR.transform, g)


def to4326(g):
    return transform(TR_INV.transform, g)


def close_ring(ring):
    return ring if ring[0] == ring[-1] else ring + [ring[0]]


def poly(rings):
    rs = [close_ring(r) for r in rings]
    return Polygon(rs[0]) if len(rs) == 1 else MultiPolygon([Polygon(r) for r in rs])


# ---------------------------------------------------------------- land_use
LAND_USE = {
    # id: (code, gb50137, name_zh, rationale, rings)
    "LU-101": ("0902", "B2_B29", "南部门户更新带", "大钟寺片区南部门户，沿京张走廊对外交通组织与商务服务",
               [[[116.34850, 39.93900], [116.35530, 39.93900], [116.35530, 39.94400], [116.34656, 39.94400]]]),
    "LU-102": ("1401", "G1_G2", "京张遗址走廊公园带", "一带主轴：京包线沿线南北连续绿带，慢行+文化+开敞测试载体",
               [[[116.34070, 39.93900], [116.34850, 39.93900], [116.34656, 39.94400], [116.34511, 39.94984],
                 [116.34465, 39.95174], [116.34381, 39.95331], [116.34205, 39.95658], [116.34020, 39.95987],
                 [116.34000, 39.96100], [116.34070, 39.96100]]]),
    "LU-103": ("0802", "A35", "北三环南科创更新带", "科创更新区，接北三环交通，小月河支流南段贯穿",
               [[[116.34511, 39.94984], [116.34465, 39.95174], [116.34381, 39.95331], [116.34205, 39.95658],
                 [116.34020, 39.95987], [116.34000, 39.96100], [116.33994, 39.96630], [116.35520, 39.96630],
                 [116.35530, 39.96500], [116.35530, 39.94984]]]),
    "LU-104": ("0802", "A35_R2", "小月河研发更新带", "依托小月河支流蓝绿廊，研发+社区更新",
               [[[116.33994, 39.96630], [116.35520, 39.96630], [116.35508, 39.96778], [116.35486, 39.97056],
                 [116.35463, 39.97333], [116.35475, 39.97460], [116.33972, 39.97460], [116.33981, 39.97100],
                 [116.33992, 39.96700]]]),
    "LU-105": ("0902", "B2_B29", "原点社区南服务带", "中核南翼服务带，衔接小月河与原点社区",
               [[[116.33972, 39.97460], [116.35475, 39.97460], [116.35441, 39.97611], [116.35419, 39.97889],
                 [116.35397, 39.98167], [116.35389, 39.98350], [116.34025, 39.98350], [116.34014, 39.98189],
                 [116.33970, 39.97500]]]),
    "LU-106": ("0702", "R22", "原点社区东西缘更新带", "重点区两翼的社区更新界面",
               [[[116.34025, 39.98350], [116.34200, 39.98350], [116.34200, 39.99350], [116.34089, 39.99350],
                 [116.34081, 39.99222], [116.34059, 39.98878], [116.34037, 39.98533]],
                [[116.35300, 39.98350], [116.35389, 39.98350], [116.35374, 39.98444], [116.35352, 39.98722],
                 [116.35330, 39.99000], [116.35349, 39.99350], [116.35300, 39.99350]]]),
    "LU-107": ("100104", "M0", "科创产业带", "原点社区—众智园之间新型产业带，轨道/路网衔接",
               [[[116.34089, 39.99350], [116.35349, 39.99350], [116.35352, 39.99406], [116.35374, 39.99811],
                 [116.35397, 40.00217], [116.35419, 40.00622], [116.35424, 40.00750], [116.34175, 40.00750],
                 [116.34170, 40.00600], [116.34148, 40.00256], [116.34126, 39.99911], [116.34103, 39.99567]]]),
    "LU-108": ("0702", "R22", "众智园东西缘更新带", "众智园两翼更新界面，东翼沿 G6 辅路",
               [[[116.34175, 40.00750], [116.34300, 40.00750], [116.34300, 40.02650], [116.34270, 40.02650],
                 [116.34259, 40.02422], [116.34248, 40.02194], [116.34237, 40.01967], [116.34226, 40.01739],
                 [116.34214, 40.01511], [116.34203, 40.01283], [116.34192, 40.01056]],
                [[116.35400, 40.00750], [116.35424, 40.00750], [116.35441, 40.01028], [116.35463, 40.01433],
                 [116.35486, 40.01839], [116.35508, 40.02244], [116.35530, 40.02650], [116.35400, 40.02650]]]),
    "LU-201": ("0902", "B2_B29", "大钟寺站城一体商务区", "站点周边高强度复合商务，国际路演客厅",
               [[[116.34656, 39.94400], [116.34900, 39.94400], [116.34900, 39.94984], [116.34511, 39.94984]]]),
    "LU-202": ("0901", "B1", "大钟寺商业文化街区", "智能体/智能终端展示、内容消费、数据要素商业界面",
               [[[116.34900, 39.94400], [116.35200, 39.94400], [116.35200, 39.94984], [116.34900, 39.94984]]]),
    "LU-203": ("0701", "R2", "大钟寺配套社区", "片区居住与社区配套，维持城市型街区肌理",
               [[[116.35200, 39.94400], [116.35530, 39.94400], [116.35530, 39.94984], [116.35200, 39.94984]]]),
    "LU-301": ("0802", "A35", "近校成果转化孵化区", "近校孵化、成果转化、法务/知产/投融资服务",
               [[[116.34200, 39.98350], [116.35300, 39.98350], [116.35300, 39.98570], [116.34200, 39.98570]]]),
    "LU-302": ("0803", "A2_A3", "成果发布与开源社区区", "开源发布厅、代码墙、成果发布，公共空间承载",
               [[[116.34200, 39.98570], [116.34800, 39.98570], [116.34800, 39.98900], [116.34200, 39.98900]]]),
    "LU-303": ("0701", "R2", "人才居住社区", "人才特区居住生活配套",
               [[[116.34200, 39.98900], [116.34800, 39.98900], [116.34800, 39.99350], [116.34200, 39.99350]]]),
    "LU-304": ("0902", "B2_B29", "产业商务服务区", "企业服务、产业平台与人才服务复合",
               [[[116.34800, 39.98570], [116.35300, 39.98570], [116.35300, 39.99350], [116.34800, 39.99350]]]),
    "LU-401": ("1401", "G1", "清河界面绿色创新廊", "临清河界面绿色开放带，低碳创新廊/雨洪/慢行复合",
               [[[116.34300, 40.02350], [116.35400, 40.02350], [116.35400, 40.02650], [116.34300, 40.02650]]]),
    "LU-402": ("100104", "M0", "全栈自主创新研发区", "国家平台、全栈自主创新研发；G6 从东缘进入",
               [[[116.34300, 40.00750], [116.34900, 40.00750], [116.34900, 40.02350], [116.34300, 40.02350]]]),
    "LU-403": ("1001", "M1_A35", "测试与安全治理区", "开放测试场、标准制定工作坊、安全治理展示",
               [[[116.34900, 40.00750], [116.35400, 40.00750], [116.35400, 40.01700], [116.34900, 40.01700]]]),
    "LU-404": ("0803", "A2_A3", "产业展示与低碳交往区", "产业展示、低碳算力体验与国际交往",
               [[[116.34900, 40.01700], [116.35400, 40.01700], [116.35400, 40.02350], [116.34900, 40.02350]]]),
}

# ---------------------------------------------------------------- buildings
BUILDINGS = {
    # id: (building_type, land_use_code, name_zh, height_range, floors, rrd, rings)
    "BLDG-ZZY-01": ("ai_r_and_d", "0802", "众智园研发办公（测试场序列起锚）", (24, 45), "6-12", "new",
                    (25000,40000), [[[116.3430, 40.0085], [116.3475, 40.0085], [116.3475, 40.0140], [116.3430, 40.0140]]]),
    "BLDG-ZZY-02": ("cultural", "0803", "众智园文化展示（安全治理展示廊）", (15, 24), "3-6", "new",
                    (8000,15000), [[[116.3465, 40.0100], [116.3500, 40.0100], [116.3500, 40.0160], [116.3465, 40.0160]]]),
    "BLDG-ZZY-03": ("ai_r_and_d", "0802", "众智园清河界面低强度研发（保留/更新）", (12, 18), "3-5", "retain",
                    (12000,20000), [[[116.3505, 40.0205], [116.3540, 40.0205], [116.3540, 40.0258], [116.3505, 40.0258]]]),
    "BLDG-ZZY-04": ("mixed_use", "0902", "众智园创新街区（院落式研发）", (18, 36), "4-9", "new",
                    (20000,30000), [[[116.3430, 40.0150], [116.3490, 40.0150], [116.3490, 40.0205], [116.3430, 40.0205]]]),
    "BLDG-ZZY-05": ("office", "1305", "众智园低碳算力驿站（端侧算力新基建）", (12, 24), "3-6", "renovate",
                    (6000,12000), [[[116.3495, 40.0080], [116.3535, 40.0080], [116.3535, 40.0135], [116.3495, 40.0135]]]),
    "BLDG-ZZY-06": ("talent_apartment", "0702", "众智园人才公寓", (24, 36), "8-12", "new",
                    (10000,16000), [[[116.3470, 40.0165], [116.3515, 40.0165], [116.3515, 40.0205], [116.3470, 40.0205]]]),
    "BLDG-YD-01": ("education", "0804", "原点社区近校成果转化驿站", (24, 36), "6-10", "new",
                   (15000,25000), [[[116.3420, 39.9840], [116.3460, 39.9840], [116.3460, 39.9875], [116.3420, 39.9875]]]),
    "BLDG-YD-02": ("cultural", "0803", "原点社区开源发布厅", (15, 20), "3-5", "new",
                   (6000,10000), [[[116.3455, 39.9860], [116.3490, 39.9860], [116.3490, 39.9900], [116.3455, 39.9900]]]),
    "BLDG-YD-03": ("talent_apartment", "0702", "原点社区人才公寓与社区服务", (30, 54), "10-18", "renovate",
                   (15000,25000), [[[116.3495, 39.9845], [116.3530, 39.9845], [116.3530, 39.9890], [116.3495, 39.9890]]]),
    "BLDG-YD-04": ("office", "0902", "原点社区成果展示发布（保留更新）", (18, 30), "5-9", "retain",
                   (10000,18000), [[[116.3425, 39.9900], [116.3465, 39.9900], [116.3465, 39.9932], [116.3425, 39.9932]]]),
    "BLDG-YD-05": ("mixed_use", "0902", "原点社区近校创新街（街区缝合）", (15, 30), "4-8", "renovate",
                   (18000,30000), [[[116.3470, 39.9900], [116.3525, 39.9900], [116.3525, 39.9932], [116.3470, 39.9932]]]),
    "BLDG-DZS-01": ("mobility_hub", "1206", "大钟寺站城一体化枢纽", (24, 60), "6-15", "renovate",
                    (20000,35000), [[[116.3435, 39.9450], [116.3475, 39.9450], [116.3475, 39.9495], [116.3435, 39.9495]]]),
    "BLDG-DZS-02": ("cultural", "0803", "大钟寺国际路演客厅（西南象限）", (15, 24), "3-6", "new",
                    (5000,9000), [[[116.3420, 39.9440], [116.3450, 39.9440], [116.3450, 39.9470], [116.3420, 39.9470]]]),
    "BLDG-DZS-03": ("retail", "0901", "大钟寺内容消费商业（东南象限）", (16, 30), "4-8", "renovate",
                    (8000,14000), [[[116.3450, 39.9440], [116.3495, 39.9440], [116.3495, 39.9470], [116.3450, 39.9470]]]),
    "BLDG-DZS-04": ("office", "0902", "大钟寺数据要素会客厅（西北象限）", (18, 36), "5-10", "renovate",
                    (10000,16000), [[[116.3420, 39.9475], [116.3460, 39.9475], [116.3460, 39.9498], [116.3420, 39.9498]]]),
    "BLDG-DZS-05": ("ai_r_and_d", "0902", "大钟寺领军企业研发总部（东北象限）", (30, 60), "8-16", "renovate",
                    (15000,25000), [[[116.3465, 39.9475], [116.3515, 39.9475], [116.3515, 39.9498], [116.3465, 39.9498]]]),
}

# ---------------------------------------------------------------- phasing
PHASING = {
    "PHASE-001": ("phase_1", "近期试点：京张遗址公园段＋原点社区近校段", "2025-2027",
                  ["JZ-01", "JZ-06"], ["PROV-KEY-002"], "廊道先行：公园/道路权属相对简单，慢行缝合与活动路线投资小见效快",
                  [[[116.3430, 39.9530], [116.3470, 39.9530], [116.3470, 40.0125], [116.3430, 40.0125]],
                   [[116.3420, 39.9835], [116.3530, 39.9835], [116.3530, 39.9935], [116.3420, 39.9935]]]),
    "PHASE-002": ("phase_2", "中期更新：众智园清河界面＋原点深化＋大钟寺站四象限", "2028-2031",
                  ["JZ-02", "JZ-03", "JZ-04"], ["PROV-KEY-001", "PROV-KEY-002", "PROV-KEY-003"],
                  "站点锚定：众智园清河界面与大钟寺站体均具强空间锚点，但依赖控规/产权/轨道一体化",
                  [[[116.3430, 40.0075], [116.3540, 40.0075], [116.3540, 40.0260], [116.3430, 40.0260]],
                   [[116.3420, 39.9835], [116.3530, 39.9835], [116.3530, 39.9935], [116.3420, 39.9935]],
                   [[116.3420, 39.9440], [116.3550, 39.9440], [116.3550, 39.94984], [116.3420, 39.94984]]]),
    "PHASE-003": ("phase_3", "长期治理：廊道全线贯通＋端侧算力网络＋活动常态化", "2032-2035+",
                  ["JZ-05", "JZ-06"], ["PROV-KEY-001", "PROV-KEY-002", "PROV-KEY-003"],
                  "权属依赖最重的跨环节点、分布式新基建与运营体系常态化",
                  [[[116.3407, 39.9390], [116.3485, 39.9390], [116.3485, 40.0265], [116.3407, 40.0265]]]),
}

# ---------------------------------------------------------------- helpers
def load_geo(name):
    return json.loads((GEO / name).read_text(encoding="utf-8"))


def site_geom():
    d = load_geo("site_boundary.geojson")
    return shape(d["features"][0]["geometry"])


def constraints_lines():
    d = load_geo("constraints.geojson")
    rail = water = None
    for f in d["features"]:
        if f["properties"]["constraint_type"] == "existing_rail":
            rail = shape(f["geometry"])
        elif f["properties"]["constraint_type"] == "existing_water":
            water = shape(f["geometry"])
    return rail, water


def split_water(water, threshold=40.0):
    """Split water MultiLineString into north (清河, y>=40.0) and south (小月河, y<40.0) lines."""
    north, south = [], []
    for line in (water.geoms if water.geom_type == "MultiLineString" else [water]):
        if line.bounds[1] >= threshold:
            north.append(line)
        else:
            south.append(line)
    return (MultiLineString(north) if len(north) > 1 else (north[0] if north else None),
            MultiLineString(south) if len(south) > 1 else (south[0] if south else None))


def buffered_in_site(line, m, site):
    if line is None:
        return None
    b = to4548(line).buffer(m)
    return to4326(b.intersection(to4548(site)))


def gen_blue_green():
    site = site_geom()
    rail, water = constraints_lines()
    water_n, water_s = split_water(water)

    greens = {
        "GREEN-001": ("京张铁路遗址公园带", "G1 公园绿地（遗址公园）", "1401", buffered_in_site(rail, 80, site), "CONSTRAINTS-001", "PROV-KEY-002/003"),
        "GREEN-002": ("清河蓝绿廊道（众智园界面段）", "蓝绿廊道", "1401", buffered_in_site(water_n, 60, site), "CONSTRAINTS-002", "PROV-KEY-001"),
        "GREEN-003": ("小月河蓝绿廊道（南段）", "蓝绿廊道", "1401", buffered_in_site(water_s, 40, site), "CONSTRAINTS-002", "PROV-KEY-002/003"),
    }
    # 独立多边形（社区/站点公园）
    greens["GREEN-004"] = ("原点社区公园", "G1 公园绿地（社区公园）", "1401",
                           poly([[[116.3460, 39.9850], [116.3505, 39.9850], [116.3505, 39.9910], [116.3460, 39.9910]]]), None, "PROV-KEY-002")
    greens["GREEN-005"] = ("大钟寺规划绿地复合利用带", "G2 防护绿地", "1402",
                           poly([[[116.3430, 39.9440], [116.3490, 39.9440], [116.3490, 39.9498], [116.3430, 39.9498]]]), None, "PROV-KEY-003")

    publics = {
        "PUBLIC-001": ("京张遗址公园公共空间活力带（南段，含南端缝合广场）", "遗址公园公共空间带", "1403",
                       buffered_in_site(rail, 30, site), "CONSTRAINTS-001", "PROV-KEY-003"),
        "PUBLIC-002": ("大钟寺站四象限步行广场", "站前广场/轨道一体化", "1403",
                       poly([[[116.3440, 39.9580], [116.3500, 39.9580], [116.3500, 39.9640], [116.3440, 39.9640]]]), None, "PROV-KEY-003"),
        "PUBLIC-003": ("众智园清河创新界面广场", "蓝绿界面广场", "1403",
                       poly([[[116.3440, 40.0140], [116.3520, 40.0140], [116.3520, 40.0200], [116.3440, 40.0200]]]), "GREEN-002", "PROV-KEY-001"),
        "PUBLIC-004": ("原点社区近校缝合广场", "近校缝合广场", "1403",
                       poly([[[116.3450, 39.9850], [116.3500, 39.9850], [116.3500, 39.9920], [116.3450, 39.9920]]]), "GREEN-004", "PROV-KEY-002"),
        "PUBLIC-005": ("遗址公园北端跨环慢行节点", "跨环路慢行节点", "1403",
                       poly([[[116.3430, 40.0210], [116.3520, 40.0210], [116.3520, 40.0265], [116.3430, 40.0265]]]), "GREEN-001", "PROV-KEY-001"),
    }
    return greens, publics


def area_sqm(g):
    return round(to4548(g).area, 1) if g is not None else None


def write_geojson(name, features):
    fc = {"type": "FeatureCollection", "name": name, "features": features}
    (GEO / name).write_text(json.dumps(fc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    import argparse
    p = argparse.ArgumentParser(description="Generate design-grade provisional geometry")
    p.add_argument(
        "--submission-dir",
        type=Path,
        default=DEFAULT_SUBMISSION,
        help="Submission package root (writes geometry/*.geojson)",
    )
    return p.parse_args()


def main() -> int:
    global GEO
    args = parse_args()
    sub = args.submission_dir if args.submission_dir.is_absolute() else REPO / args.submission_dir
    GEO = sub / "geometry"
    if not (GEO / "site_boundary.geojson").is_file():
        print(f"ERROR: {GEO / 'site_boundary.geojson'} missing; run sync_submission_boundary.py first", file=sys.stderr)
        return 1
    if not (GEO / "constraints.geojson").is_file():
        print(f"ERROR: {GEO / 'constraints.geojson'} missing; run sync_submission_constraints.py first", file=sys.stderr)
        return 1

    site = site_geom()
    features_landuse = []
    for lid, (code, gb, name, rationale, rings) in LAND_USE.items():
        g = poly(rings).buffer(0).intersection(site.buffer(0))
        features_landuse.append({
            "type": "Feature", "id": lid,
            "properties": {"id": lid, "layer": "LAND_USE", "source_type": "agent_generated_design",
                           "confidence": "medium", "geometry_role": "design_proposal",
                           "provisional": True, "official_boundary": False,
                           "land_use_code": code, "land_use_code_gb50137": gb,
                           "name_zh": name, "design_rationale": rationale, "area_sqm_declared": area_sqm(g)},
            "geometry": json.loads(json.dumps(g.__geo_interface__)),
        })
    # 拓扑清理：互斥化（消重叠）→ gap 并入（最长接触块）→ buffer(0)（修自交），迭代至达标
    gs_4548 = [to4548(shape(f["geometry"])) for f in features_landuse]
    site4548 = to4548(site)
    for _ in range(6):
        acc = None
        cleaned = []
        for g in gs_4548:
            g = g.buffer(0)
            if acc is not None:
                g = g.difference(acc)
            cleaned.append(g)
            acc = cleaned[0] if acc is None else acc.union(g)
        gs_4548 = cleaned
        union = unary_union(gs_4548)
        diff = site4548.difference(union)
        if not diff.is_empty:
            diffs = list(diff.geoms) if diff.geom_type == "MultiPolygon" else [diff]
            for gp in diffs:
                best = max(range(len(gs_4548)),
                           key=lambda i: gs_4548[i].boundary.intersection(gp.boundary).length)
                gs_4548[best] = gs_4548[best].union(gp).buffer(0)
        if site4548.difference(unary_union(gs_4548)).area < 0.5:
            break
    for i, f in enumerate(features_landuse):
        g4326 = make_valid(to4326(gs_4548[i])).buffer(0)
        if not transform(TR.transform, g4326).is_valid:
            g4326 = transform(TR_INV.transform, transform(TR.transform, g4326).buffer(0.001))
        f["geometry"] = json.loads(json.dumps(g4326.__geo_interface__))
        f["properties"]["area_sqm_declared"] = round(gs_4548[i].area, 1)
    write_geojson("land_use.geojson", features_landuse)
    print(f"land_use: {len(features_landuse)} features (topology-cleaned)")

    features_build = []
    for bid, (btype, code, name, (hmin, hmax), floors, rrd, (amin, amax), rings) in BUILDINGS.items():
        g = poly(rings).buffer(0).intersection(site.buffer(0))
        if not g.is_empty:
            from shapely import affinity
            cur = to4548(g).area
            if cur > 0:
                target = (amin + amax) / 2.0
                fct = (target / cur) ** 0.5
                g = to4326(affinity.scale(to4548(g), xfact=fct, yfact=fct, origin="center"))
        features_build.append({
            "type": "Feature", "id": bid,
            "properties": {"id": bid, "layer": "BUILDING_FOOTPRINT",
                           "source_type": "agent_generated_design", "confidence": "medium",
                           "geometry_role": "design_proposal", "building_type": btype,
                           "land_use_code": code, "name_zh": name,
                           "height_m": round((hmin + hmax) / 2, 1),
                           "height_range_m": [hmin, hmax], "floors": floors,
                           "status": "provisional", "control_status": "pending_regulatory_confirmation",
                           "retain_renovate_demolish": rrd, "area_sqm_declared": area_sqm(g)},
            "geometry": json.loads(json.dumps(g.__geo_interface__)),
        })
    write_geojson("buildings.geojson", features_build)
    print(f"buildings: {len(features_build)} features")

    greens, publics = gen_blue_green()
    fg = []
    for gid, (name, gtype, code, g, csid, kaid) in greens.items():
        fg.append({"type": "Feature", "id": gid,
                   "properties": {"id": gid, "layer": "GREEN_SPACE", "source_type": "agent_generated_design",
                                  "confidence": "medium", "geometry_role": "design_proposal",
                                  "land_use_code": code, "green_type": gtype, "name_zh": name,
                                  "area_sqm_declared": area_sqm(g), "constraint_source_id": csid,
                                  "key_area_id": kaid,
                                  "official_boundary": False, "boundary_precision": "provisional_rough",
                                  "provisional_note": "基于天地图1:100万真实水系/铁路线位缓冲示意，位置中误差100-500m；官方蓝线发布后整体重算"},
                   "geometry": json.loads(json.dumps(g.__geo_interface__))})
    write_geojson("green_space.geojson", fg)
    print(f"green_space: {len(fg)} features")

    fp = []
    for pid, (name, stype, code, g, lgid, kaid) in publics.items():
        fp.append({"type": "Feature", "id": pid,
                   "properties": {"id": pid, "layer": "PUBLIC_SPACE", "source_type": "agent_generated_design",
                                  "confidence": "medium", "geometry_role": "design_proposal",
                                  "land_use_code": code, "space_type": stype, "name_zh": name,
                                  "area_sqm_declared": area_sqm(g), "linked_green_id": lgid,
                                  "key_area_id": kaid,
                                  "official_boundary": False, "boundary_precision": "provisional_rough",
                                  "provisional_note": "provisional 公共空间节点；正式边界与上位规划待官方数据"},
                   "geometry": json.loads(json.dumps(g.__geo_interface__))})
    write_geojson("public_space.geojson", fp)
    print(f"public_space: {len(fp)} features")

    fph = []
    for pid, (phase, name, horizon, jz, kaids, dep, rings) in PHASING.items():
        g = poly(rings).buffer(0).intersection(site.buffer(0))
        fph.append({"type": "Feature", "id": pid,
                    "properties": {"id": pid, "layer": "PHASE", "source_type": "agent_generated_design",
                                   "confidence": "medium", "geometry_role": "design_proposal",
                                   "provisional_constraint": True, "official_boundary": False,
                                   "boundary_precision": "provisional_rough", "phase": phase,
                                   "phase_order": int(phase.split("_")[1]), "name_zh": name,
                                   "phase_horizon": horizon, "related_jz_projects": jz,
                                   "key_area_ids": kaids, "implementation_dependency": dep,
                                   "area_sqm_declared": area_sqm(g)},
                    "geometry": json.loads(json.dumps(g.__geo_interface__))})
    write_geojson("phasing.geojson", fph)
    print(f"phasing: {len(fph)} features")

    # ---- topology report ----
    lu4326 = [shape(f["geometry"]).buffer(0) for f in features_landuse]
    lu4548 = [to4548(g) for g in lu4326]
    union = unary_union(lu4548)
    site4548 = to4548(site)
    overlap = sum(
        lu4548[i].intersection(lu4548[j]).area
        for i in range(len(lu4548))
        for j in range(i + 1, len(lu4548))
    )
    gap = site4548.area - union.area
    print(f"topology: union={round(union.area,1)} site={round(site4548.area,1)} "
          f"gap={round(gap,1)} overlap={round(overlap,1)}")
    if abs(gap) > 10.0 or overlap > 10.0:
        print(f"ERROR: land_use topology |gap|={abs(gap):.1f} m² overlap={overlap:.1f} m² exceeds 10 m² tolerance", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
