"""test_land_use_validator.py — 建设许可组合机（三线 × 三区）测试。

覆盖：
  1. ALLOWED：城镇空间 + 三线全过
  2. 三线拒：红线/农田/边界违规 → DENIED_BY_LINE（三区编排器不运行）
  3. 三区拒：三线全过但主导为生态/农业空间 → DENIED_BY_ZONE（用途管制禁令）
  4. 三重 fail-closed 传染：输入无效 / 三线未决 / 三区未决
  5. 全链证据聚合：三层证据一次取齐（三线子机 + 三区子机 + 组合机）
  6. 快捷属性 allowed / denied 语义
  7. 配置自检 + 确定性 + GeoJSON 输入

数据构造约定：
  三线：红线/农田必须位于边界外、彼此不相交（顶点接触面积 0 不算）；
  三区：三区区域是独立数据层，与三线边界无关。
"""

import pytest
from shapely.geometry import box

from constraints.state_machines.land_use_validator import (
    LAND_USE_ORCHESTRATOR,
    LandUseState,
    judge_land_use,
)
from constraints.state_machines.three_lines import Parcel, ThreeLinesBoundaries
from constraints.state_machines.three_zones import ThreeZonesRegions

PARCEL = Parcel("p1", box(0, 0, 10, 10))  # 面积 100 ㎡

FAR_A = box(100, 100, 110, 110)
FAR_B = box(200, 200, 210, 210)

# ── 三线数据 ──
LINES_OK = ThreeLinesBoundaries(
    basic_farmland=FAR_A,
    ecological_redline=FAR_B,
    urban_boundary=box(-50, -50, 50, 50),
)
LINES_REDLINE = ThreeLinesBoundaries(
    basic_farmland=FAR_A,
    ecological_redline=box(5, 5, 15, 15),   # 触地块，位于边界外
    urban_boundary=box(-5, -5, 5, 5),
)
LINES_FARMLAND = ThreeLinesBoundaries(
    basic_farmland=box(2, 2, 5, 5),         # 触地块
    ecological_redline=box(5, 5, 8, 8),     # 顶点接触农田（面积 0），不重叠
    urban_boundary=FAR_A,                   # 远处（农田优先短路，边界不评估）
)
LINES_OUTSIDE = ThreeLinesBoundaries(
    basic_farmland=FAR_A,
    ecological_redline=FAR_B,
    urban_boundary=box(-5, -5, 5, 5),       # 地块大部分在边界外
)
LINES_MISSING_REDLINE = ThreeLinesBoundaries(
    basic_farmland=FAR_A,
    ecological_redline=None,
    urban_boundary=box(-50, -50, 50, 50),
)

# ── 三区数据 ──
URBAN_DOMINANT = ThreeZonesRegions(
    ecological_zone=FAR_A,
    agricultural_zone=FAR_B,
    urban_zone=box(-50, -50, 50, 50),
)
ECO_DOMINANT = ThreeZonesRegions(
    ecological_zone=box(-50, -50, 6, 10),   # 60%
    agricultural_zone=box(6, -50, 10, 50),  # 40%
    urban_zone=FAR_A,
)
AGRI_DOMINANT = ThreeZonesRegions(
    ecological_zone=box(6, -50, 10, 50),
    agricultural_zone=box(-50, -50, 6, 10),
    urban_zone=FAR_A,
)
TIE_ZONES = ThreeZonesRegions(
    ecological_zone=box(-50, -50, 5, 10),   # 50%
    agricultural_zone=box(5, -50, 10, 50),  # 50%
    urban_zone=FAR_A,
)
MISSING_ZONE = ThreeZonesRegions(
    ecological_zone=None,
    agricultural_zone=FAR_A,
    urban_zone=box(-50, -50, 50, 50),
)


def assert_state(verdict, expect: LandUseState, completed: bool = True) -> None:
    assert verdict.run.completed == completed
    assert verdict.run.final_state is expect, f"final={verdict.run.final_state}，期望 {expect}"


# ═══════════════════════════════════════════════════════════════════
# 1. ALLOWED：城镇空间 + 三线全过
# ═══════════════════════════════════════════════════════════════════

def test_urban_zone_and_lines_clear_allows_building():
    v = judge_land_use(PARCEL, LINES_OK, URBAN_DOMINANT)
    assert v.allowed
    assert not v.denied
    assert_state(v, LandUseState.BUILDING_ALLOWED)
    assert v.violations == ()


# ═══════════════════════════════════════════════════════════════════
# 2. 三线拒 → DENIED_BY_LINE（三区编排器不运行）
# ═══════════════════════════════════════════════════════════════════

def test_redline_violation_denies_without_zones_check():
    v = judge_land_use(PARCEL, LINES_REDLINE, URBAN_DOMINANT)
    assert v.denied and not v.allowed
    assert_state(v, LandUseState.DENIED_BY_LINE)
    # 硬约束短路：三区编排器不应运行
    assert v.three_zones is None
    # 违规证据上浮（红线条款 + 量化面积）
    assert any(
        e.rule_id == "redline_encroach" and e.regulation.doc_short == "自然资发〔2022〕142号"
        and dict(e.metric)["redline_overlap_area_sqm"] > 0
        for e in v.violations
    )


def test_farmland_violation_denies_with_highest_priority():
    v = judge_land_use(PARCEL, LINES_FARMLAND, URBAN_DOMINANT)
    assert_state(v, LandUseState.DENIED_BY_LINE)
    assert v.three_zones is None
    assert any(e.rule_id == "basic_farmland_encroach" for e in v.violations)


def test_outside_boundary_denies():
    v = judge_land_use(PARCEL, LINES_OUTSIDE, URBAN_DOMINANT)
    assert_state(v, LandUseState.DENIED_BY_LINE)
    assert v.three_zones is None
    assert any(e.rule_id == "urban_boundary_encroach" for e in v.violations)


# ═══════════════════════════════════════════════════════════════════
# 3. 三区拒：生态/农业空间不得变更为建设用地
# ═══════════════════════════════════════════════════════════════════

def test_ecological_dominant_zone_denies():
    v = judge_land_use(PARCEL, LINES_OK, ECO_DOMINANT)
    assert v.denied and not v.allowed
    assert_state(v, LandUseState.DENIED_BY_ZONE)
    # 三区编排器已运行并给出生态结论
    assert v.three_zones is not None and v.three_zones.completed
    # 用途管制禁令证据（中发〔2019〕18号）
    ban = [e for e in v.violations if e.rule_id == "zone_building_ban"]
    assert len(ban) == 1
    assert "生态空间" in ban[0].detail
    assert ban[0].regulation.doc_short == "中发〔2019〕18号"


def test_agricultural_dominant_zone_denies():
    v = judge_land_use(PARCEL, LINES_OK, AGRI_DOMINANT)
    assert_state(v, LandUseState.DENIED_BY_ZONE)
    ban = [e for e in v.violations if e.rule_id == "zone_building_ban"]
    assert len(ban) == 1 and "农业空间" in ban[0].detail


# ═══════════════════════════════════════════════════════════════════
# 4. 三重 fail-closed 传染
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "parcel,lines,zones,label",
    [
        (Parcel("p-none", None), LINES_OK, URBAN_DOMINANT, "输入无效（地块几何缺失）"),
        (PARCEL, LINES_MISSING_REDLINE, URBAN_DOMINANT, "三线未决（红线数据缺失）"),
        (PARCEL, LINES_OK, TIE_ZONES, "三区未决（占比并列）"),
        (PARCEL, LINES_OK, MISSING_ZONE, "三区未决（区域数据缺失）"),
    ],
)
def test_fail_closed_propagation(parcel, lines, zones, label):
    v = judge_land_use(parcel, lines, zones)
    assert not v.allowed and not v.denied
    assert_state(v, LandUseState.FAIL_CLOSED, completed=False)
    # 未决必须有违规证据且引用条款
    assert v.violations
    assert all(e.regulation.doc_short for e in v.violations), label


# ═══════════════════════════════════════════════════════════════════
# 5. 全链证据聚合
# ═══════════════════════════════════════════════════════════════════

def test_allowed_full_evidence_chain():
    v = judge_land_use(PARCEL, LINES_OK, URBAN_DOMINANT)
    ids = [e.rule_id for e in v.evidences]
    # 三线子机（农田/红线/边界）+ 三区子机（城镇主导）+ 组合机两层
    for expected in (
        "farmland_verified", "redline_verified", "boundary_verified",
        "dominant_urban", "lines_allowed", "zones_dominant_urban",
    ):
        assert expected in ids, f"证据链缺少 {expected}"
    # 每条证据都有条款引用
    assert all(e.regulation.doc_short for e in v.evidences)


def test_denied_violations_aggregate_across_layers():
    v = judge_land_use(PARCEL, LINES_OK, ECO_DOMINANT)
    ids = {e.rule_id for e in v.violations}
    # 三区子机的违规（无——三区自身判定合规）+ 组合机用途管制禁令
    assert "zone_building_ban" in ids
    assert "no_unique_dominant" not in ids


# ═══════════════════════════════════════════════════════════════════
# 6. 快捷属性语义
# ═══════════════════════════════════════════════════════════════════

def test_verdict_quick_properties():
    assert judge_land_use(PARCEL, LINES_OK, URBAN_DOMINANT).allowed is True
    assert judge_land_use(PARCEL, LINES_REDLINE, URBAN_DOMINANT).denied is True
    assert judge_land_use(PARCEL, LINES_OK, ECO_DOMINANT).denied is True
    assert judge_land_use(PARCEL, LINES_MISSING_REDLINE, URBAN_DOMINANT).allowed is False
    assert judge_land_use(PARCEL, LINES_MISSING_REDLINE, URBAN_DOMINANT).denied is False


# ═══════════════════════════════════════════════════════════════════
# 7. 配置自检 + 确定性 + GeoJSON 输入
# ═══════════════════════════════════════════════════════════════════

def test_configuration_valid():
    assert LAND_USE_ORCHESTRATOR.validate() == []


def test_determinism_same_input_same_output():
    assert judge_land_use(PARCEL, LINES_OK, URBAN_DOMINANT) == judge_land_use(PARCEL, LINES_OK, URBAN_DOMINANT)
    assert judge_land_use(PARCEL, LINES_REDLINE, URBAN_DOMINANT) == judge_land_use(PARCEL, LINES_REDLINE, URBAN_DOMINANT)


def test_geojson_feature_input():
    feature = {
        "type": "Feature",
        "properties": {"id": "p-json", "proposed_use_code": "R2"},
        "geometry": {"type": "Polygon",
                     "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
    }
    parcel = Parcel.from_geojson_feature(feature)
    assert parcel.proposed_use_code == "R2"
    v = judge_land_use(parcel, LINES_OK, URBAN_DOMINANT)
    assert v.allowed
