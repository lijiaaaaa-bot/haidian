"""test_three_lines.py — 三线判定机与编排器测试。

覆盖（对齐冒烟用例并扩展）：
  1. 基本判定：ALLOWED / 红线拒绝 / 农田拒绝 / 边界外拒绝
  2. 边界接触（面积 0）不违规
  3. 合规证据链完整性（每条证据有条款引用）
  4. 数据缺失 fail-closed（三条线各缺一次）
  5. 三线数据自相交叉 fail-closed（三种两两组合）
  6. 优先级短路（农田 > 红线 > 边界，低优先子机不运行）
  7. 三个子机独立运行
  8. 无效输入 fail-closed（geometry=None、GeoJSON 非法）
  9. GeoJSON feature 输入
  10. 违规证据带量化指标（重叠面积 > 0）
  11. 确定性：同输入两次运行结果逐位一致
  12. 转换表配置自检干净（validate）
  13. 基类强制 evidence：无条款引用的 guard 一律拒绝

数据构造约定（与冒烟测试相同）：
  红线/农田必须位于城镇开发边界之外、彼此不相交（顶点接触面积 0 不算），
  否则触发"三线互不交叉"数据一致性校验（合法行为）。
"""

import pytest
from shapely.geometry import box

from constraints.state_machines.state_machine import EvidenceOutcome, Guard, GuardResult, SYSTEM_FAIL_CLOSED
from constraints.state_machines.three_lines import (
    AREA_EPSILON,
    EcologicalRedlineMachine,
    EcologicalRedlineState,
    JudgementContext,
    Parcel,
    PermanentBasicFarmlandMachine,
    PermanentBasicFarmlandState,
    ThreeLinesBoundaries,
    ThreeLinesOrchestrator,
    ThreeLinesState,
    UrbanDevelopmentBoundaryMachine,
    UrbanDevelopmentBoundaryState,
    judge_three_lines,
)

PARCEL = Parcel("p1", box(0, 0, 10, 10))


def b(
    farmland: tuple[float, float, float, float] | None = (100, 100, 110, 110),
    redline: tuple[float, float, float, float] | None = (200, 200, 210, 210),
    boundary: tuple[float, float, float, float] | None = (-50, -50, 50, 50),
) -> ThreeLinesBoundaries:
    """构造三线边界；传 None 表示该线数据缺失。"""
    return ThreeLinesBoundaries(
        basic_farmland=box(*farmland) if farmland else None,
        ecological_redline=box(*redline) if redline else None,
        urban_boundary=box(*boundary) if boundary else None,
    )


# ═══════════════════════════════════════════════════════════════════
# 1. 基本判定
# ═══════════════════════════════════════════════════════════════════

def test_all_lines_clear_allows_construction():
    run = judge_three_lines(PARCEL, b())
    assert run.completed
    assert run.final_state is ThreeLinesState.ALLOWED
    assert run.violations == ()


def test_redline_overlap_rejects():
    run = judge_three_lines(PARCEL, b(redline=(5, 5, 15, 15), boundary=(-5, -5, 5, 5)))
    assert run.completed
    assert run.final_state is ThreeLinesState.REJECTED_ECOLOGICAL_REDLINE


def test_farmland_overlap_rejects():
    run = judge_three_lines(PARCEL, b(farmland=(2, 2, 5, 5), redline=(5, 5, 8, 8), boundary=(100, 100, 110, 110)))
    assert run.completed
    assert run.final_state is ThreeLinesState.REJECTED_BASIC_FARMLAND


def test_outside_urban_boundary_rejects():
    run = judge_three_lines(PARCEL, b(boundary=(-5, -5, 5, 5)))
    assert run.completed
    assert run.final_state is ThreeLinesState.REJECTED_OUTSIDE_BOUNDARY


# ═══════════════════════════════════════════════════════════════════
# 2. 边界接触（面积 0）不违规
# ═══════════════════════════════════════════════════════════════════

def test_vertex_touching_redline_is_not_encroachment():
    # 地块右上角 (10,10) 与红线左下角顶点接触，重叠面积 0
    run = judge_three_lines(PARCEL, b(redline=(10, 10, 20, 20), boundary=(-5, -5, 10, 10)))
    assert run.completed
    assert run.final_state is ThreeLinesState.ALLOWED
    # 证据中重叠面积应 ≤ AREA_EPSILON
    assert all(m[1] <= AREA_EPSILON for e in run.evidences for m in e.metric)


# ═══════════════════════════════════════════════════════════════════
# 3. 合规证据链完整性
# ═══════════════════════════════════════════════════════════════════

def test_allow_evidence_chain_complete():
    run = judge_three_lines(PARCEL, b())
    assert run.final_state is ThreeLinesState.ALLOWED
    assert len(run.evidences) >= 3  # 农田 + 红线 + 边界 各一条判定证据
    for e in run.evidences:
        assert e.outcome is EvidenceOutcome.COMPLIANT
        assert e.regulation.doc_short, f"证据 {e.rule_id} 缺少条款引用"
        assert e.detail
    assert run.violations == ()


# ═══════════════════════════════════════════════════════════════════
# 4. 数据缺失 fail-closed（不确定即拒）
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "missing,label",
    [
        ("farmland", "永久基本农田"),
        ("redline", "生态保护红线"),
        ("boundary", "城镇开发边界"),
    ],
)
def test_missing_line_data_fails_closed(missing: str, label: str):
    kwargs = {"farmland": (100, 100, 110, 110), "redline": (200, 200, 210, 210), "boundary": (-50, -50, 50, 50)}
    kwargs[missing] = None
    run = judge_three_lines(PARCEL, b(**kwargs))
    assert not run.completed, f"{label}数据缺失应 fail-closed"
    assert run.final_state is ThreeLinesState.FAIL_CLOSED
    # 未决必须有违规证据（引用 fail-closed 原则）
    assert run.violations
    assert all(e.regulation.doc_short for e in run.violations)


# ═══════════════════════════════════════════════════════════════════
# 5. 三线数据自相交叉 fail-closed（互不交叉、不重叠、不冲突）
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "farmland,redline,boundary",
    [
        ((5, 5, 15, 15), (10, 10, 20, 20), (100, 100, 110, 110)),  # 农田 ∩ 红线
        ((5, 5, 15, 15), (200, 200, 210, 210), (10, 10, 20, 20)),  # 农田 ∩ 边界
        ((100, 100, 110, 110), (5, 5, 15, 15), (10, 10, 20, 20)),  # 红线 ∩ 边界
    ],
)
def test_crossing_lines_fail_closed(farmland, redline, boundary):
    run = judge_three_lines(PARCEL, b(farmland=farmland, redline=redline, boundary=boundary))
    assert not run.completed
    assert run.final_state is ThreeLinesState.FAIL_CLOSED
    # 违规证据引用"三线互不交叉"原则
    assert any(e.rule_id == "three_lines_inconsistent" for e in run.violations)


# ═══════════════════════════════════════════════════════════════════
# 6. 优先级短路：永久基本农田 > 生态保护红线 > 城镇开发边界
# ═══════════════════════════════════════════════════════════════════

def _transition_names(run) -> list[str]:
    return [s.transition_name for s in run.steps]


def test_farmland_priority_over_redline_short_circuits():
    # 农田 + 红线都触碰地块 → 只报农田，红线子机不运行
    run = judge_three_lines(
        PARCEL, b(farmland=(2, 2, 5, 5), redline=(5, 5, 8, 8), boundary=(100, 100, 110, 110)))
    assert run.completed
    assert run.final_state is ThreeLinesState.REJECTED_BASIC_FARMLAND
    names = _transition_names(run)
    assert not any("redline" in n or "boundary" in n for n in names), f"低优先子机不应运行: {names}"
    # 违规证据只含农田条款
    assert all(e.rule_id == "basic_farmland_encroach" for e in run.violations)


def test_redline_priority_over_boundary_short_circuits():
    # 红线 + 超出边界 → 只报红线，边界子机不运行
    run = judge_three_lines(PARCEL, b(redline=(5, 5, 15, 15), boundary=(-5, -5, 5, 5)))
    assert run.completed
    assert run.final_state is ThreeLinesState.REJECTED_ECOLOGICAL_REDLINE
    names = _transition_names(run)
    assert not any("boundary" in n for n in names), f"边界子机不应运行: {names}"
    assert all(e.rule_id == "redline_encroach" for e in run.violations)


def test_farmland_priority_over_all_short_circuits():
    # 农田 + 红线 + 超出边界 → 只报农田
    run = judge_three_lines(
        PARCEL, b(farmland=(2, 2, 5, 5), redline=(5, 5, 8, 8), boundary=(-5, -5, 2, 2)))
    assert run.completed
    assert run.final_state is ThreeLinesState.REJECTED_BASIC_FARMLAND
    assert all(e.rule_id == "basic_farmland_encroach" for e in run.violations)


# ═══════════════════════════════════════════════════════════════════
# 7. 三个子机独立运行
# ═══════════════════════════════════════════════════════════════════

def test_sub_machines_run_independently():
    # 农田子机：触线拒绝 / 未触线通过
    run = PermanentBasicFarmlandMachine().run(
        JudgementContext(parcel=PARCEL, boundaries=b(farmland=(2, 2, 5, 5))))
    assert run.completed and run.final_state is PermanentBasicFarmlandState.REJECTED
    run = PermanentBasicFarmlandMachine().run(JudgementContext(parcel=PARCEL, boundaries=b()))
    assert run.completed and run.final_state is PermanentBasicFarmlandState.VERIFIED

    # 红线子机
    run = EcologicalRedlineMachine().run(
        JudgementContext(parcel=PARCEL, boundaries=b(redline=(5, 5, 15, 15))))
    assert run.completed and run.final_state is EcologicalRedlineState.REJECTED
    run = EcologicalRedlineMachine().run(JudgementContext(parcel=PARCEL, boundaries=b()))
    assert run.completed and run.final_state is EcologicalRedlineState.VERIFIED

    # 边界子机
    run = UrbanDevelopmentBoundaryMachine().run(
        JudgementContext(parcel=PARCEL, boundaries=b(boundary=(-5, -5, 5, 5))))
    assert run.completed and run.final_state is UrbanDevelopmentBoundaryState.REJECTED
    run = UrbanDevelopmentBoundaryMachine().run(JudgementContext(parcel=PARCEL, boundaries=b()))
    assert run.completed and run.final_state is UrbanDevelopmentBoundaryState.VERIFIED


def test_sub_machine_missing_boundary_fails_closed():
    run = EcologicalRedlineMachine().run(
        JudgementContext(parcel=PARCEL, boundaries=b(redline=None)))
    assert not run.completed
    assert run.final_state is EcologicalRedlineState.FAIL_CLOSED


# ═══════════════════════════════════════════════════════════════════
# 8. 无效输入 fail-closed
# ═══════════════════════════════════════════════════════════════════

def test_none_geometry_fails_closed():
    run = judge_three_lines(Parcel("p-none", None), b())
    assert not run.completed
    assert run.final_state is ThreeLinesState.FAIL_CLOSED


def test_invalid_geojson_geometry_fails_closed():
    feature = {
        "type": "Feature",
        "properties": {"id": "p-bad"},
        "geometry": {"type": "Polygon", "coordinates": "not-a-coordinate-list"},
    }
    parcel = Parcel.from_geojson_feature(feature)
    assert parcel.geometry is None
    run = judge_three_lines(parcel, b())
    assert not run.completed
    assert run.final_state is ThreeLinesState.FAIL_CLOSED


# ═══════════════════════════════════════════════════════════════════
# 9. GeoJSON feature 输入
# ═══════════════════════════════════════════════════════════════════

def test_geojson_feature_input():
    feature = {
        "type": "Feature",
        "properties": {"id": "p-json"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        },
    }
    parcel = Parcel.from_geojson_feature(feature)
    assert parcel.parcel_id == "p-json"
    run = judge_three_lines(parcel, b())
    assert run.completed
    assert run.final_state is ThreeLinesState.ALLOWED


# ═══════════════════════════════════════════════════════════════════
# 10. 违规证据带量化指标
# ═══════════════════════════════════════════════════════════════════

def test_violation_carries_quantified_metric():
    run = judge_three_lines(PARCEL, b(redline=(5, 5, 15, 15), boundary=(-5, -5, 5, 5)))
    assert run.final_state is ThreeLinesState.REJECTED_ECOLOGICAL_REDLINE
    assert len(run.violations) == 1
    ev = run.violations[0]
    metrics = dict(ev.metric)
    assert "redline_overlap_area_sqm" in metrics
    assert metrics["redline_overlap_area_sqm"] > AREA_EPSILON


def test_outside_boundary_metric_reports_area():
    run = judge_three_lines(PARCEL, b(boundary=(-5, -5, 5, 5)))
    assert run.final_state is ThreeLinesState.REJECTED_OUTSIDE_BOUNDARY
    assert dict(run.violations[0].metric)["outside_boundary_area_sqm"] > 0


# ═══════════════════════════════════════════════════════════════════
# 11. 确定性：同输入两次运行逐位一致
# ═══════════════════════════════════════════════════════════════════

def test_determinism_same_input_same_output():
    boundaries = b(redline=(5, 5, 15, 15), boundary=(-5, -5, 5, 5))
    run1 = judge_three_lines(PARCEL, boundaries)
    run2 = judge_three_lines(PARCEL, boundaries)
    assert run1 == run2
    assert run1.final_state == run2.final_state
    assert run1.evidences == run2.evidences


# ═══════════════════════════════════════════════════════════════════
# 12. 转换表配置自检
# ═══════════════════════════════════════════════════════════════════

def test_orchestrator_configuration_valid():
    assert ThreeLinesOrchestrator().validate() == []


def test_sub_machine_configuration_valid():
    assert EcologicalRedlineMachine().validate() == []
    assert PermanentBasicFarmlandMachine().validate() == []
    assert UrbanDevelopmentBoundaryMachine().validate() == []


# ═══════════════════════════════════════════════════════════════════
# 13. 基类强制 evidence：无条款引用的 guard 一律拒绝
# ═══════════════════════════════════════════════════════════════════

def test_guard_without_regulations_fails_closed():
    guard = Guard(guard_id="no_citation", regulations=(), check=lambda ctx: GuardResult.ok())
    result = guard.evaluate(object())
    assert not result.passed
    assert result.evidences[0].regulation is SYSTEM_FAIL_CLOSED
    assert "未绑定任何法条引用" in result.evidences[0].detail


def test_guard_exception_fails_closed():
    def boom(_ctx):
        raise RuntimeError("geometry failure")

    guard = Guard(guard_id="boom", regulations=(SYSTEM_FAIL_CLOSED,), check=boom)
    result = guard.evaluate(object())
    assert not result.passed
    assert result.evidences[0].outcome is EvidenceOutcome.VIOLATION
    assert "按 fail-closed 拒绝" in result.evidences[0].detail
