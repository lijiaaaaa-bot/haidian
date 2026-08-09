"""test_three_zones.py — 三区判定机与编排器测试。

覆盖：
  1. 基本分类：完全位于单一空间（生态/农业/城镇）
  2. 面积占比主导（60/40 各种组合）
  3. 无优先级编码：60% 农业 / 40% 城镇 → 农业（不存在"城镇优先"隐性规则）
  4. 并列（50/50）→ fail-closed（不猜）
  5. 全零（与所有空间均无重叠）→ fail-closed
  6. 区域数据缺失 → fail-closed（三个区各缺一次）
  7. 输入无效（地块几何 None / 退化地块）→ fail-closed
  8. 三个子机独立运行（从属/无从属/数据缺失）
  9. 证据链：分类证据带三个占比指标 + 条款引用
  10. 编排器结论入册（ctx.three_zones_verdict）
  11. 配置自检 + 确定性

数据构造约定：
  区域接缝处共享边界（重叠面积 0）不算互相重叠；地块 box(0,0,10,10) 面积 100，
  box(-50,-50,6,10) 覆盖 x∈[0,6) = 60㎡（60%），box(6,-50,10,50) 覆盖 x∈[6,10] = 40㎡。
"""

import pytest
from shapely.geometry import Polygon, box

from constraints.state_machines.three_lines import Parcel, ThreeLinesBoundaries, ThreeLinesOrchestrator
from constraints.state_machines.three_zones import (
    AgriculturalZoneMachine,
    AgriculturalZoneState,
    EcologicalZoneMachine,
    EcologicalZoneState,
    ThreeZonesOrchestrator,
    ThreeZonesRegions,
    ThreeZonesState,
    UrbanZoneMachine,
    UrbanZoneState,
    ZoneJudgementContext,
    judge_three_zones,
)

PARCEL = Parcel("p1", box(0, 0, 10, 10))  # 面积 100 ㎡

ECO = box(-50, -50, 50, 50)
AGRI = box(-50, -50, 50, 50)
URBAN = box(-50, -50, 50, 50)
FAR_A = box(100, 100, 110, 110)   # 远处（不与地块重叠）
FAR_B = box(200, 200, 210, 210)


def z(eco=None, agri=None, urban=None) -> ThreeZonesRegions:
    return ThreeZonesRegions(ecological_zone=eco, agricultural_zone=agri, urban_zone=urban)


def assert_verdict(run, expect_completed: bool, expect_state: ThreeZonesState) -> None:
    assert run.completed == expect_completed, f"completed={run.completed}，期望 {expect_completed}"
    assert run.final_state is expect_state, f"final={run.final_state}，期望 {expect_state}"


# ═══════════════════════════════════════════════════════════════════
# 1-3. 基本分类 + 面积占比主导 + 无优先级编码
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "eco,agri,urban,expect",
    [
        # ── 完全位于单一空间 ──
        (ECO, FAR_A, FAR_B, ThreeZonesState.ECOLOGICAL),
        (FAR_A, ECO, FAR_B, ThreeZonesState.AGRICULTURAL),
        (FAR_A, FAR_B, ECO, ThreeZonesState.URBAN),
        # ── 面积占比主导（60/40）──
        (box(-50, -50, 6, 10), box(6, -50, 10, 50), FAR_B, ThreeZonesState.ECOLOGICAL),
        (box(6, -50, 10, 50), box(-50, -50, 6, 10), FAR_B, ThreeZonesState.AGRICULTURAL),
        (box(-50, -50, 6, 10), FAR_A, box(6, -50, 10, 50), ThreeZonesState.ECOLOGICAL),
        # ── 无优先级编码：60% 农业 / 40% 城镇 → 农业（面积主导，非"城镇优先"）──
        (FAR_A, box(-50, -50, 6, 10), box(6, -50, 10, 50), ThreeZonesState.AGRICULTURAL),
        # 60% 生态 / 40% 城镇 → 生态
        (box(-50, -50, 6, 10), FAR_A, box(6, -50, 10, 50), ThreeZonesState.ECOLOGICAL),
    ],
)
def test_dominant_classification(eco, agri, urban, expect):
    run = judge_three_zones(PARCEL, z(eco=eco, agri=agri, urban=urban))
    assert_verdict(run, True, expect)
    assert run.violations == ()


# ═══════════════════════════════════════════════════════════════════
# 4. 并列 → fail-closed（不猜）
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "eco,agri,urban",
    [
        (box(-50, -50, 5, 10), box(5, -50, 10, 50), FAR_B),  # 生态 50 / 农业 50
        (box(-50, -50, 5, 10), FAR_A, box(5, -50, 10, 50)),  # 生态 50 / 城镇 50
        (FAR_A, box(-50, -50, 5, 10), box(5, -50, 10, 50)),  # 农业 50 / 城镇 50
    ],
)
def test_tie_fails_closed(eco, agri, urban):
    run = judge_three_zones(PARCEL, z(eco=eco, agri=agri, urban=urban))
    assert_verdict(run, False, ThreeZonesState.FAIL_CLOSED)
    assert any(e.rule_id == "no_unique_dominant" for e in run.violations)


# ═══════════════════════════════════════════════════════════════════
# 5. 全零（与所有空间均无重叠）→ fail-closed
# ═══════════════════════════════════════════════════════════════════

def test_no_overlap_with_any_zone_fails_closed():
    run = judge_three_zones(PARCEL, z(eco=FAR_A, agri=FAR_B, urban=box(300, 300, 310, 310)))
    assert_verdict(run, False, ThreeZonesState.FAIL_CLOSED)
    assert any(e.rule_id == "no_unique_dominant" for e in run.violations)


# ═══════════════════════════════════════════════════════════════════
# 6. 区域数据缺失 → fail-closed（不确定即拒）
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("missing", ["eco", "agri", "urban"])
def test_missing_zone_data_fails_closed(missing: str):
    kwargs = {"eco": ECO, "agri": FAR_A, "urban": FAR_B}
    kwargs[missing] = None
    run = judge_three_zones(PARCEL, z(**kwargs))
    assert_verdict(run, False, ThreeZonesState.FAIL_CLOSED)
    assert any(e.rule_id == "zone_measurement_failed" for e in run.violations)


# ═══════════════════════════════════════════════════════════════════
# 7. 输入无效 → fail-closed
# ═══════════════════════════════════════════════════════════════════

def test_none_geometry_fails_closed():
    run = judge_three_zones(Parcel("p-none", None), z(eco=ECO, agri=FAR_A, urban=FAR_B))
    assert_verdict(run, False, ThreeZonesState.FAIL_CLOSED)


def test_degenerate_geometry_fails_closed():
    # 退化多边形（面积 0）→ 无法计算占比 → fail-closed
    degenerate = Parcel("p-degenerate", Polygon([(0, 0), (0, 0), (0, 0)]))
    run = judge_three_zones(degenerate, z(eco=ECO, agri=FAR_A, urban=FAR_B))
    assert_verdict(run, False, ThreeZonesState.FAIL_CLOSED)
    assert any(e.rule_id == "zone_measurement_failed" for e in run.violations)


# ═══════════════════════════════════════════════════════════════════
# 8. 三个子机独立运行
# ═══════════════════════════════════════════════════════════════════

def test_sub_machines_run_independently():
    in_eco = ZoneJudgementContext(parcel=PARCEL, boundaries=ThreeLinesBoundaries(),
                                  zones=z(eco=ECO, agri=FAR_A, urban=FAR_B))
    assert EcologicalZoneMachine().run(in_eco).final_state is EcologicalZoneState.OVERLAPS
    assert AgriculturalZoneMachine().run(in_eco).final_state is AgriculturalZoneState.DISJOINT
    assert UrbanZoneMachine().run(in_eco).final_state is UrbanZoneState.DISJOINT

    in_agri = ZoneJudgementContext(parcel=PARCEL, boundaries=ThreeLinesBoundaries(),
                                   zones=z(eco=FAR_A, agri=ECO, urban=FAR_B))
    assert AgriculturalZoneMachine().run(in_agri).final_state is AgriculturalZoneState.OVERLAPS
    assert EcologicalZoneMachine().run(in_agri).final_state is EcologicalZoneState.DISJOINT

    in_urban = ZoneJudgementContext(parcel=PARCEL, boundaries=ThreeLinesBoundaries(),
                                    zones=z(eco=FAR_A, agri=FAR_B, urban=ECO))
    assert UrbanZoneMachine().run(in_urban).final_state is UrbanZoneState.OVERLAPS


def test_sub_machine_missing_zone_fails_closed():
    ctx = ZoneJudgementContext(parcel=PARCEL, boundaries=ThreeLinesBoundaries(),
                               zones=z(eco=None, agri=FAR_A, urban=FAR_B))
    run = EcologicalZoneMachine().run(ctx)
    assert not run.completed
    assert run.final_state is EcologicalZoneState.FAIL_CLOSED


# ═══════════════════════════════════════════════════════════════════
# 9. 证据链：分类证据带三个占比指标 + 条款引用
# ═══════════════════════════════════════════════════════════════════

def test_dominant_evidence_carries_ratios_and_citation():
    run = judge_three_zones(
        PARCEL, z(eco=box(-50, -50, 6, 10), agri=box(6, -50, 10, 50), urban=FAR_B))
    assert run.final_state is ThreeZonesState.ECOLOGICAL
    dominant = [e for e in run.evidences if e.rule_id == "dominant_ecological"]
    assert len(dominant) == 1
    metrics = dict(dominant[0].metric)
    assert metrics["ecological_ratio"] == pytest.approx(0.6)
    assert metrics["agricultural_ratio"] == pytest.approx(0.4)
    assert metrics["urban_ratio"] == 0.0
    assert dominant[0].regulation.doc_short == "中发〔2019〕18号"
    assert dominant[0].outcome.value == "compliant"


# ═══════════════════════════════════════════════════════════════════
# 10. 编排器结论入册（供组合机 land_use_validator 读取）
# ═══════════════════════════════════════════════════════════════════

def test_orchestrator_writes_verdict_into_context():
    ctx = ZoneJudgementContext(parcel=PARCEL, boundaries=ThreeLinesBoundaries(),
                               zones=z(eco=ECO, agri=FAR_A, urban=FAR_B))
    run = ThreeZonesOrchestrator().run(ctx)
    assert ctx.three_zones_verdict is run


# ═══════════════════════════════════════════════════════════════════
# 11. 配置自检 + 确定性 + GeoJSON 输入
# ═══════════════════════════════════════════════════════════════════

def test_configuration_valid():
    assert ThreeZonesOrchestrator().validate() == []
    assert EcologicalZoneMachine().validate() == []
    assert AgriculturalZoneMachine().validate() == []
    assert UrbanZoneMachine().validate() == []


def test_determinism_same_input_same_output():
    regions = z(eco=box(-50, -50, 6, 10), agri=box(6, -50, 10, 50), urban=FAR_B)
    assert judge_three_zones(PARCEL, regions) == judge_three_zones(PARCEL, regions)


def test_geojson_feature_input():
    feature = {
        "type": "Feature",
        "properties": {"id": "p-json"},
        "geometry": {"type": "Polygon",
                     "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
    }
    run = judge_three_zones(Parcel.from_geojson_feature(feature), z(eco=ECO, agri=FAR_A, urban=FAR_B))
    assert_verdict(run, True, ThreeZonesState.ECOLOGICAL)


def test_zone_verdict_composable_with_three_lines():
    """三区判定与三线判定可在同一 context 上组合（verdict 互不干扰）。"""
    ctx = ZoneJudgementContext(
        parcel=PARCEL,
        boundaries=ThreeLinesBoundaries(
            basic_farmland=FAR_A, ecological_redline=FAR_B, urban_boundary=box(-50, -50, 50, 50)),
        zones=z(eco=ECO, agri=FAR_A, urban=FAR_B),
    )
    ThreeLinesOrchestrator().run(ctx)
    ThreeZonesOrchestrator().run(ctx)
    assert ctx.three_lines_verdict is not None and ctx.three_lines_verdict.completed
    assert ctx.three_zones_verdict is not None and ctx.three_zones_verdict.completed
