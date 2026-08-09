"""three_lines.py — "三线"判定子机与编排器。

Domain source: notes/01-territorial-spatial-planning.md §三线详细定义

三个判定子机（可独立运行）：
  - EcologicalRedlineMachine        生态保护红线：重叠即拒（开发性建设）
  - PermanentBasicFarmlandMachine   永久基本农田：重叠即拒（未经国务院批准不得占用）
  - UrbanDevelopmentBoundaryMachine 城镇开发边界：地块必须完全位于边界内

编排器 ThreeLinesOrchestrator（组合运行）：
  转换表声明顺序即优先级 —— 永久基本农田 > 生态保护红线 > 城镇开发边界。
  高优先级子机判定拒绝后立即短路，低优先级子机不再运行（三线互不交叉的
  正常数据下，地块不可能同时违反两条线；若数据自相交叉，编排器 fail-closed）。

设计决策：
  - 子机采用"先 measure 后判定"两步：action 预计算几何指标写入
    JudgementContext 类型化字段，guard 只读纯数据（几何只算一次，
    guard 保持纯谓词）。
  - 子机结果通过 record_* / 类型化 property 存入共享 results dict，
    编排器 guard 读取 —— 替代裸字符串 ctx.load(...) 散落调用。
  - fail-closed 传染：子机未决/异常 → 编排器 FAIL_CLOSED 终态；
    边界数据缺失 → 视为"不确定"，拒绝而非假设不存在。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, cast

from shapely import Geometry
from shapely.geometry import shape

from .state_machine import (
    Evidence,
    EvidenceOutcome,
    Guard,
    GuardResult,
    MachineContext,
    MachineRun,
    Regulation,
    StateMachine,
    Transition,
    _fail_closed_evidence,
)

# ═══════════════════════════════════════════════════════════════════
# 条款常量 —— 强制 evidence 的来源（固定中文文案，非生成文本）
# Source: notes/01-territorial-spatial-planning.md §三线详细定义
# ═══════════════════════════════════════════════════════════════════

REG_ECOLOGICAL_REDLINE = Regulation(
    doc_short="自然资发〔2022〕142号",
    doc_title_zh="自然资源部关于加强生态保护红线管理的通知（试行）",
    article_zh="管控要求",
    rule_zh=(
        "生态保护红线内严格禁止开发性、生产性建设活动，"
        "仅允许不破坏生态功能的有限人为活动"
    ),
)

REG_BASIC_FARMLAND = Regulation(
    doc_short="《土地管理法》第33-35条",
    doc_title_zh="中华人民共和国土地管理法（第三十三条至第三十五条）",
    article_zh="第三十三条至第三十五条",
    rule_zh="永久基本农田依法划定，未经国务院批准不得占用、不得开发",
)

REG_URBAN_BOUNDARY = Regulation(
    doc_short="中办国办〔2019〕指导意见",
    doc_title_zh="关于在国土空间规划中统筹划定落实三条控制线的指导意见",
    article_zh="三线管控要求",
    rule_zh="城镇开发边界内方可开展集中城镇建设，所有建设用地不得突破城镇开发边界",
)

REG_LINES_DISJOINT = Regulation(
    doc_short="中办国办〔2019〕指导意见",
    doc_title_zh="关于在国土空间规划中统筹划定落实三条控制线的指导意见",
    article_zh="三线协调原则",
    rule_zh="三条控制线互不交叉、不重叠、不冲突",
)

# 浮点/坐标精度兜底（平方米），非管控宽容度。
# 重叠面积 ≤ AREA_EPSILON 视为未占用（边界线接触不算侵入）。
AREA_EPSILON = 1e-6


# ═══════════════════════════════════════════════════════════════════
# 输入类型
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Parcel:
    """待判定地块。geometry 为 None 表示输入无效 → 各判定按 fail-closed 拒绝。"""
    parcel_id: str
    geometry: Geometry | None
    proposed_use_code: str = ""  # 拟议建设用地类型代码（三区/建设许可机使用）

    @classmethod
    def from_geojson_feature(cls, feature: dict, parcel_id: str | None = None) -> "Parcel":
        """从 GeoJSON feature 构造地块。geometry 缺失/非法 → None（fail-closed 输入）。"""
        props = feature.get("properties") or {}
        geom_raw = feature.get("geometry")
        try:
            geom: Geometry | None = shape(geom_raw) if geom_raw is not None else None
        except Exception:  # noqa: BLE001 — 非法几何按无效输入处理
            geom = None
        return cls(
            parcel_id=parcel_id or str(props.get("id", "")),
            geometry=geom,
            proposed_use_code=str(props.get("proposed_use_code", "")),
        )


@dataclass(frozen=True)
class ThreeLinesBoundaries:
    """三线边界集合。任一字段为 None 表示该线数据缺失 → 相关判定 fail-closed。

    HARD: 三条控制线互不交叉、不重叠、不冲突（中办国办〔2019〕指导意见）。
    """
    basic_farmland: Geometry | None = None      # 永久基本农田
    ecological_redline: Geometry | None = None  # 生态保护红线
    urban_boundary: Geometry | None = None      # 城镇开发边界


# ═══════════════════════════════════════════════════════════════════
# JudgementContext —— 类型化共享工作簿
# ═══════════════════════════════════════════════════════════════════

@dataclass(kw_only=True)
class JudgementContext(MachineContext):
    """三线判定共享上下文。

    - parcel / boundaries：输入（子机与编排器只读）
    - *_overlap_area / outside_boundary_area：子机 measure action 预计算
      的几何指标（类型化字段，guard 只读）
    - *_run：子机 MachineRun 结果，经 record_* 写入 results dict，
      由类型化 property 读取 —— 组合机制，无裸字符串散落
    """
    parcel: Parcel
    boundaries: ThreeLinesBoundaries

    # 几何预计算（measure action 写入）
    farmland_overlap_area: float | None = None
    redline_overlap_area: float | None = None
    outside_boundary_area: float | None = None

    # results dict 内部键（仅此处定义，其余代码一律经 property/方法访问）
    KEY_FARMLAND_RUN = "run.basic_farmland"
    KEY_REDLINE_RUN = "run.ecological_redline"
    KEY_BOUNDARY_RUN = "run.urban_boundary"
    KEY_THREE_LINES_VERDICT = "verdict.three_lines"  # 编排器结论（供组合机 land_use_validator 读取）

    # ── 类型化 property：子机结果存取 ──
    @property
    def farmland_run(self) -> MachineRun["PermanentBasicFarmlandState"] | None:
        return cast("MachineRun[PermanentBasicFarmlandState] | None", self.results.get(self.KEY_FARMLAND_RUN))

    @property
    def redline_run(self) -> MachineRun["EcologicalRedlineState"] | None:
        return cast("MachineRun[EcologicalRedlineState] | None", self.results.get(self.KEY_REDLINE_RUN))

    @property
    def boundary_run(self) -> MachineRun["UrbanDevelopmentBoundaryState"] | None:
        return cast("MachineRun[UrbanDevelopmentBoundaryState] | None", self.results.get(self.KEY_BOUNDARY_RUN))

    def record_farmland_run(self, run: MachineRun["PermanentBasicFarmlandState"]) -> None:
        self.results[self.KEY_FARMLAND_RUN] = run

    def record_redline_run(self, run: MachineRun["EcologicalRedlineState"]) -> None:
        self.results[self.KEY_REDLINE_RUN] = run

    def record_boundary_run(self, run: MachineRun["UrbanDevelopmentBoundaryState"]) -> None:
        self.results[self.KEY_BOUNDARY_RUN] = run

    # ── 编排器结论入册（ThreeLinesOrchestrator.run 自动写入，供组合机读取）──
    @property
    def three_lines_verdict(self) -> MachineRun["ThreeLinesState"] | None:
        return cast("MachineRun[ThreeLinesState] | None", self.results.get(self.KEY_THREE_LINES_VERDICT))

    def record_three_lines_verdict(self, run: MachineRun["ThreeLinesState"]) -> None:
        self.results[self.KEY_THREE_LINES_VERDICT] = run


# ═══════════════════════════════════════════════════════════════════
# 几何判定辅助
# ═══════════════════════════════════════════════════════════════════

def _overlap_area(a: Geometry | None, b: Geometry | None) -> float | None:
    """两几何重叠面积；任一缺失 → None（无法判定，调用方 fail-closed）。"""
    if a is None or b is None:
        return None
    return a.intersection(b).area


def _outside_area(parcel: Geometry | None, boundary: Geometry | None) -> float | None:
    """地块落在边界外的面积；边界缺失 → None。"""
    if parcel is None or boundary is None:
        return None
    return parcel.difference(boundary).area


# ═══════════════════════════════════════════════════════════════════
# Guard 工厂 —— 子机判定 guard（先 measure 后判定，guard 只读纯数据）
# ═══════════════════════════════════════════════════════════════════

def _make_line_guards(
    *,
    guard_prefix: str,
    regulation: Regulation,
    metric_name: str,
    violation_detail: str,
    compliant_detail: str,
    get_metric: Callable[[JudgementContext], float | None],
) -> tuple[Guard[JudgementContext], Guard[JudgementContext]]:
    """生成一对互补 guard：(encroach 触线即拒, clear 未触线通过)。

    两者必居其一；数据缺失时两者都 fail → 子机 step 无匹配 → fail-closed。
    """
    encroach_id = f"{guard_prefix}_encroach"
    clear_id = f"{guard_prefix}_clear"

    # guard passed 表示"该事实成立"→ 对应转换触发；证据的 outcome 描述事实性质。
    def check_encroach(ctx: JudgementContext) -> GuardResult:
        metric = get_metric(ctx)
        if metric is None:
            return GuardResult.fail(_fail_closed_evidence(
                encroach_id, f"缺少地块几何或边界数据，无法计算 {metric_name}，按 fail-closed 拒绝"))
        if metric > AREA_EPSILON:
            # 确认"地块触线"事实 → 触发拒绝转换；证据本身是违规记录
            return GuardResult.ok(Evidence(
                rule_id=encroach_id, outcome=EvidenceOutcome.VIOLATION,
                regulation=regulation, detail=violation_detail,
                metric=((metric_name, metric),)))
        return GuardResult.fail(Evidence(
            rule_id=encroach_id, outcome=EvidenceOutcome.COMPLIANT,
            regulation=regulation, detail=compliant_detail,
            metric=((metric_name, metric),)))

    def check_clear(ctx: JudgementContext) -> GuardResult:
        metric = get_metric(ctx)
        if metric is None:
            return GuardResult.fail(_fail_closed_evidence(
                clear_id, f"缺少地块几何或边界数据，无法计算 {metric_name}，按 fail-closed 拒绝"))
        if metric <= AREA_EPSILON:
            # 确认"地块未触线"事实 → 触发通过转换
            return GuardResult.ok(Evidence(
                rule_id=clear_id, outcome=EvidenceOutcome.COMPLIANT,
                regulation=regulation, detail=compliant_detail,
                metric=((metric_name, metric),)))
        return GuardResult.fail(Evidence(
            rule_id=clear_id, outcome=EvidenceOutcome.VIOLATION,
            regulation=regulation, detail=violation_detail,
            metric=((metric_name, metric),)))

    return (
        Guard(guard_id=encroach_id, regulations=(regulation,),
              check=check_encroach, description_zh=violation_detail),
        Guard(guard_id=clear_id, regulations=(regulation,),
              check=check_clear, description_zh=compliant_detail),
    )


# ═══════════════════════════════════════════════════════════════════
# 子机一：生态保护红线
# Source: 自然资发〔2022〕142号 —— 红线内严格禁止开发性、生产性建设活动
# ═══════════════════════════════════════════════════════════════════

class EcologicalRedlineState(Enum):
    PENDING = "pending"
    MEASURED = "measured"
    VERIFIED = "verified"
    REJECTED = "rejected"
    FAIL_CLOSED = "fail_closed"


def _measure_redline(ctx: JudgementContext) -> None:
    """action：预计算地块与生态保护红线的重叠面积。"""
    ctx.redline_overlap_area = _overlap_area(ctx.parcel.geometry, ctx.boundaries.ecological_redline)


_REDLINE_ENCROACH_GUARD, _REDLINE_CLEAR_GUARD = _make_line_guards(
    guard_prefix="redline",
    regulation=REG_ECOLOGICAL_REDLINE,
    metric_name="redline_overlap_area_sqm",
    violation_detail="地块与生态保护红线重叠，红线内严格禁止开发性、生产性建设活动",
    compliant_detail="地块未重叠生态保护红线",
    get_metric=lambda ctx: ctx.redline_overlap_area,
)


class EcologicalRedlineMachine(StateMachine[EcologicalRedlineState, JudgementContext]):
    """生态保护红线判定子机（可独立运行）。

    判定链：PENDING →(measure)→ MEASURED →(重叠)→ REJECTED / →(未重叠)→ VERIFIED
    """
    machine_id = "ecological_redline"
    state_enum = EcologicalRedlineState
    initial_state = EcologicalRedlineState.PENDING
    fail_closed_state = EcologicalRedlineState.FAIL_CLOSED

    transitions: tuple[Transition[EcologicalRedlineState, JudgementContext], ...] = (
        Transition(
            name="measure_redline",
            from_state=EcologicalRedlineState.PENDING,
            to_state=EcologicalRedlineState.MEASURED,
            action=_measure_redline,
            description_zh="计算地块与生态保护红线的重叠面积",
        ),
        Transition(
            name="redline_encroach",
            from_state=EcologicalRedlineState.MEASURED,
            to_state=EcologicalRedlineState.REJECTED,
            guards=(_REDLINE_ENCROACH_GUARD,),
            description_zh="地块重叠生态保护红线 → 禁止开发性建设",
        ),
        Transition(
            name="redline_clear",
            from_state=EcologicalRedlineState.MEASURED,
            to_state=EcologicalRedlineState.VERIFIED,
            guards=(_REDLINE_CLEAR_GUARD,),
            description_zh="地块未触及生态保护红线",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 子机二：永久基本农田（三条控制线中最优先）
# Source: 《土地管理法》第33-35条 —— 未经国务院批准不得占用
# ═══════════════════════════════════════════════════════════════════

class PermanentBasicFarmlandState(Enum):
    PENDING = "pending"
    MEASURED = "measured"
    VERIFIED = "verified"
    REJECTED = "rejected"
    FAIL_CLOSED = "fail_closed"


def _measure_farmland(ctx: JudgementContext) -> None:
    """action：预计算地块与永久基本农田的重叠面积。"""
    ctx.farmland_overlap_area = _overlap_area(ctx.parcel.geometry, ctx.boundaries.basic_farmland)


_FARMLAND_ENCROACH_GUARD, _FARMLAND_CLEAR_GUARD = _make_line_guards(
    guard_prefix="basic_farmland",
    regulation=REG_BASIC_FARMLAND,
    metric_name="farmland_overlap_area_sqm",
    violation_detail="地块与永久基本农田重叠，未经国务院批准不得占用、不得开发",
    compliant_detail="地块未重叠永久基本农田",
    get_metric=lambda ctx: ctx.farmland_overlap_area,
)


class PermanentBasicFarmlandMachine(StateMachine[PermanentBasicFarmlandState, JudgementContext]):
    """永久基本农田判定子机（可独立运行）。"""
    machine_id = "basic_farmland"
    state_enum = PermanentBasicFarmlandState
    initial_state = PermanentBasicFarmlandState.PENDING
    fail_closed_state = PermanentBasicFarmlandState.FAIL_CLOSED

    transitions: tuple[Transition[PermanentBasicFarmlandState, JudgementContext], ...] = (
        Transition(
            name="measure_farmland",
            from_state=PermanentBasicFarmlandState.PENDING,
            to_state=PermanentBasicFarmlandState.MEASURED,
            action=_measure_farmland,
            description_zh="计算地块与永久基本农田的重叠面积",
        ),
        Transition(
            name="basic_farmland_encroach",
            from_state=PermanentBasicFarmlandState.MEASURED,
            to_state=PermanentBasicFarmlandState.REJECTED,
            guards=(_FARMLAND_ENCROACH_GUARD,),
            description_zh="地块重叠永久基本农田 → 拒绝",
        ),
        Transition(
            name="basic_farmland_clear",
            from_state=PermanentBasicFarmlandState.MEASURED,
            to_state=PermanentBasicFarmlandState.VERIFIED,
            guards=(_FARMLAND_CLEAR_GUARD,),
            description_zh="地块未重叠永久基本农田",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 子机三：城镇开发边界
# Source: 中办国办〔2019〕指导意见 —— 建设用地不得突破城镇开发边界
# ═══════════════════════════════════════════════════════════════════

class UrbanDevelopmentBoundaryState(Enum):
    PENDING = "pending"
    MEASURED = "measured"
    VERIFIED = "verified"
    REJECTED = "rejected"
    FAIL_CLOSED = "fail_closed"


def _measure_boundary(ctx: JudgementContext) -> None:
    """action：预计算地块位于城镇开发边界外的面积。"""
    ctx.outside_boundary_area = _outside_area(ctx.parcel.geometry, ctx.boundaries.urban_boundary)


_BOUNDARY_ENCROACH_GUARD, _BOUNDARY_CLEAR_GUARD = _make_line_guards(
    guard_prefix="urban_boundary",
    regulation=REG_URBAN_BOUNDARY,
    metric_name="outside_boundary_area_sqm",
    violation_detail="地块超出城镇开发边界，建设用地不得突破边界",
    compliant_detail="地块全部位于城镇开发边界内",
    get_metric=lambda ctx: ctx.outside_boundary_area,
)


class UrbanDevelopmentBoundaryMachine(StateMachine[UrbanDevelopmentBoundaryState, JudgementContext]):
    """城镇开发边界判定子机（可独立运行）。"""
    machine_id = "urban_boundary"
    state_enum = UrbanDevelopmentBoundaryState
    initial_state = UrbanDevelopmentBoundaryState.PENDING
    fail_closed_state = UrbanDevelopmentBoundaryState.FAIL_CLOSED

    transitions: tuple[Transition[UrbanDevelopmentBoundaryState, JudgementContext], ...] = (
        Transition(
            name="measure_boundary",
            from_state=UrbanDevelopmentBoundaryState.PENDING,
            to_state=UrbanDevelopmentBoundaryState.MEASURED,
            action=_measure_boundary,
            description_zh="计算地块位于城镇开发边界外的面积",
        ),
        Transition(
            name="urban_boundary_encroach",
            from_state=UrbanDevelopmentBoundaryState.MEASURED,
            to_state=UrbanDevelopmentBoundaryState.REJECTED,
            guards=(_BOUNDARY_ENCROACH_GUARD,),
            description_zh="地块超出城镇开发边界 → 拒绝",
        ),
        Transition(
            name="urban_boundary_clear",
            from_state=UrbanDevelopmentBoundaryState.MEASURED,
            to_state=UrbanDevelopmentBoundaryState.VERIFIED,
            guards=(_BOUNDARY_CLEAR_GUARD,),
            description_zh="地块全部位于城镇开发边界内",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 编排器：ThreeLinesOrchestrator
# 转换表声明顺序即优先级：基本农田 → 生态红线 → 城镇开发边界（短路）
# ═══════════════════════════════════════════════════════════════════

class ThreeLinesState(Enum):
    PENDING = "pending"
    FARMLAND_CHECKED = "farmland_checked"
    REDLINE_CHECKED = "redline_checked"
    BOUNDARY_CHECKED = "boundary_checked"
    ALLOWED = "allowed"                                     # 三线全部通过（三线维度可建设）
    REJECTED_BASIC_FARMLAND = "rejected_basic_farmland"     # 违反最高优先控制线
    REJECTED_ECOLOGICAL_REDLINE = "rejected_ecological_redline"
    REJECTED_OUTSIDE_BOUNDARY = "rejected_outside_boundary"
    FAIL_CLOSED = "fail_closed"                             # 数据非法/缺失/未决 → 传染


# ── 数据一致性 guard：三线互不交叉、不重叠、不冲突 ──

def _three_lines_intersect(ctx: JudgementContext) -> bool:
    """三线两两交叉检查（缺失的线跳过；判定交给对应子机 fail-closed）。"""
    b = ctx.boundaries
    pairs = (
        (b.basic_farmland, b.ecological_redline),
        (b.basic_farmland, b.urban_boundary),
        (b.ecological_redline, b.urban_boundary),
    )
    return any(
        a is not None and c is not None and a.intersection(c).area > AREA_EPSILON
        for a, c in pairs
    )


def _check_lines_inconsistent(ctx: JudgementContext) -> GuardResult:
    if _three_lines_intersect(ctx):
        return GuardResult.ok(Evidence(
            rule_id="three_lines_inconsistent",
            outcome=EvidenceOutcome.VIOLATION,
            regulation=REG_LINES_DISJOINT,
            detail="三条控制线边界数据互相交叉或重叠，违反'互不交叉、不重叠、不冲突'原则，判定结果不可信",
        ))
    return GuardResult.fail(Evidence(
        rule_id="three_lines_consistent",
        outcome=EvidenceOutcome.COMPLIANT,
        regulation=REG_LINES_DISJOINT,
        detail="三条控制线边界数据互不交叉",
    ))


_LINES_INCONSISTENT_GUARD = Guard(
    guard_id="three_lines_inconsistent",
    regulations=(REG_LINES_DISJOINT,),
    check=_check_lines_inconsistent,
    description_zh="三线数据一致性校验：互不交叉、不重叠、不冲突",
)


# ── 子机结论 guard 工厂：rejected / fail_closed / verified 三选一（互补） ──

RunGetter = Callable[[JudgementContext], MachineRun[Any] | None]


def _make_sub_verdict_guards(
    *,
    prefix: str,
    regulation: Regulation,
    reject_state: Enum,
    verified_state: Enum,
    run_getter: RunGetter,
    machine_label: str,
) -> tuple[Guard[JudgementContext], Guard[JudgementContext], Guard[JudgementContext]]:
    """生成 (rejected, fail_closed, verified) 三个互补 guard。

    - rejected：子机确定拒绝 → 通过（evidence 直接上浮子机违规证据，
      条款与面积全部保留，构成完整证据链）。
    - fail_closed：子机未决/异常 → 通过（fail-closed 传染到编排器）。
    - verified：子机通过 → 通过，进入下一优先级判定。
    子机未运行时三者皆不通过 → 编排器 step 无匹配 → fail-closed。
    """
    def check_rejected(ctx: JudgementContext) -> GuardResult:
        run = run_getter(ctx)
        if run is None:
            return GuardResult.fail(_fail_closed_evidence(
                f"{prefix}_rejected", f"{machine_label}子机未运行，无法判定"))
        if not run.completed:
            return GuardResult.fail(Evidence(
                rule_id=f"{prefix}_rejected", outcome=EvidenceOutcome.COMPLIANT,
                regulation=regulation, detail=f"{machine_label}子机未得出确定结论", metric=()))
        if run.final_state is reject_state:
            return GuardResult.ok(*run.violations)  # 上浮子机违规证据
        return GuardResult.fail(Evidence(
            rule_id=f"{prefix}_rejected", outcome=EvidenceOutcome.COMPLIANT,
            regulation=regulation, detail=f"{machine_label}子机结论不是拒绝", metric=()))

    def check_fail_closed(ctx: JudgementContext) -> GuardResult:
        run = run_getter(ctx)
        if run is None:
            return GuardResult.fail(_fail_closed_evidence(
                f"{prefix}_fail_closed", f"{machine_label}子机未运行，无法判定"))
        if not run.completed:
            return GuardResult.ok(_fail_closed_evidence(
                f"{prefix}_fail_closed", f"{machine_label}子机 fail-closed（未决），编排器按 fail-closed 传染拒绝"))
        return GuardResult.fail(Evidence(
            rule_id=f"{prefix}_fail_closed", outcome=EvidenceOutcome.COMPLIANT,
            regulation=regulation, detail=f"{machine_label}子机已得出确定结论", metric=()))

    def check_verified(ctx: JudgementContext) -> GuardResult:
        run = run_getter(ctx)
        if run is None:
            return GuardResult.fail(_fail_closed_evidence(
                f"{prefix}_verified", f"{machine_label}子机未运行，无法判定"))
        if not run.completed:
            return GuardResult.fail(_fail_closed_evidence(
                f"{prefix}_verified", f"{machine_label}子机未决，不得判定通过"))
        if run.final_state is verified_state:
            return GuardResult.ok(Evidence(
                rule_id=f"{prefix}_verified", outcome=EvidenceOutcome.COMPLIANT,
                regulation=regulation, detail=f"{machine_label}判定通过",
                metric=()))
        return GuardResult.fail(Evidence(
            rule_id=f"{prefix}_verified", outcome=EvidenceOutcome.VIOLATION,
            regulation=regulation, detail=f"{machine_label}判定为拒绝", metric=()))

    return (
        Guard(guard_id=f"{prefix}_rejected", regulations=(regulation,),
              check=check_rejected, description_zh=f"{machine_label}子机判定拒绝"),
        Guard(guard_id=f"{prefix}_fail_closed", regulations=(regulation,),
              check=check_fail_closed, description_zh=f"{machine_label}子机 fail-closed 传染"),
        Guard(guard_id=f"{prefix}_verified", regulations=(regulation,),
              check=check_verified, description_zh=f"{machine_label}子机判定通过"),
    )


_FARMLAND_REJECTED, _FARMLAND_FAIL_CLOSED, _FARMLAND_VERIFIED = _make_sub_verdict_guards(
    prefix="farmland",
    regulation=REG_BASIC_FARMLAND,
    reject_state=PermanentBasicFarmlandState.REJECTED,
    verified_state=PermanentBasicFarmlandState.VERIFIED,
    run_getter=lambda ctx: ctx.farmland_run,
    machine_label="永久基本农田",
)

_REDLINE_REJECTED, _REDLINE_FAIL_CLOSED, _REDLINE_VERIFIED = _make_sub_verdict_guards(
    prefix="redline",
    regulation=REG_ECOLOGICAL_REDLINE,
    reject_state=EcologicalRedlineState.REJECTED,
    verified_state=EcologicalRedlineState.VERIFIED,
    run_getter=lambda ctx: ctx.redline_run,
    machine_label="生态保护红线",
)

_BOUNDARY_REJECTED, _BOUNDARY_FAIL_CLOSED, _BOUNDARY_VERIFIED = _make_sub_verdict_guards(
    prefix="boundary",
    regulation=REG_URBAN_BOUNDARY,
    reject_state=UrbanDevelopmentBoundaryState.REJECTED,
    verified_state=UrbanDevelopmentBoundaryState.VERIFIED,
    run_getter=lambda ctx: ctx.boundary_run,
    machine_label="城镇开发边界",
)


# ── 编排器 action：运行子机并把结果记入共享工作簿 ──

_FARMLAND_MACHINE = PermanentBasicFarmlandMachine()
_REDLINE_MACHINE = EcologicalRedlineMachine()
_BOUNDARY_MACHINE = UrbanDevelopmentBoundaryMachine()


def _run_farmland_machine(ctx: JudgementContext) -> None:
    ctx.record_farmland_run(_FARMLAND_MACHINE.run(ctx))


def _run_redline_machine(ctx: JudgementContext) -> None:
    ctx.record_redline_run(_REDLINE_MACHINE.run(ctx))


def _run_boundary_machine(ctx: JudgementContext) -> None:
    ctx.record_boundary_run(_BOUNDARY_MACHINE.run(ctx))


class ThreeLinesOrchestrator(StateMachine[ThreeLinesState, JudgementContext]):
    """三线组合编排器：地块 → 三线逐线判定 → 综合结论。

    转换表声明顺序即优先级（永久基本农田 > 生态保护红线 > 城镇开发边界）：
    高优先级子机拒绝 → 立即进入对应拒绝终态，低优先级子机不再运行。
    """
    machine_id = "three_lines"
    state_enum = ThreeLinesState
    initial_state = ThreeLinesState.PENDING

    def run(self, ctx: JudgementContext) -> MachineRun[ThreeLinesState]:
        """运行编排器，FAIL_CLOSED 终态归一为 completed=False（未决即拒），
        并把结论自动写入 ctx（供组合机 land_use_validator 读取）。

        基类中 FAIL_CLOSED 是无出边的合法终态（completed=True）；但对外语义
        上"未决"必须与"正常拒绝（REJECTED_*）"区分——前者 completed=False。
        """
        run = super().run(ctx)
        if run.final_state is ThreeLinesState.FAIL_CLOSED and run.completed:
            run = MachineRun(
                machine_id=self.machine_id, completed=False,
                final_state=run.final_state, steps=run.steps,
            )
        ctx.record_three_lines_verdict(run)
        return run

    transitions: tuple[Transition[ThreeLinesState, JudgementContext], ...] = (
        # ── 数据一致性（输入非法 → fail-closed，判定结果不可信） ──
        Transition(
            name="three_lines_data_inconsistent",
            from_state=ThreeLinesState.PENDING,
            to_state=ThreeLinesState.FAIL_CLOSED,
            guards=(_LINES_INCONSISTENT_GUARD,),
            description_zh="三线边界数据互相交叉/重叠 → 输入非法，fail-closed",
        ),
        # ── 第一优先：永久基本农田 ──
        Transition(
            name="check_farmland",
            from_state=ThreeLinesState.PENDING,
            to_state=ThreeLinesState.FARMLAND_CHECKED,
            guards=(),
            action=_run_farmland_machine,
            description_zh="运行永久基本农田子机（最高优先级）",
        ),
        Transition(
            name="reject_basic_farmland",
            from_state=ThreeLinesState.FARMLAND_CHECKED,
            to_state=ThreeLinesState.REJECTED_BASIC_FARMLAND,
            guards=(_FARMLAND_REJECTED,),
            description_zh="地块重叠永久基本农田 → 拒绝（最高优先）",
        ),
        Transition(
            name="farmland_fail_closed",
            from_state=ThreeLinesState.FARMLAND_CHECKED,
            to_state=ThreeLinesState.FAIL_CLOSED,
            guards=(_FARMLAND_FAIL_CLOSED,),
            description_zh="永久基本农田子机未决 → fail-closed 传染",
        ),
        Transition(
            name="farmland_verified_next",
            from_state=ThreeLinesState.FARMLAND_CHECKED,
            to_state=ThreeLinesState.REDLINE_CHECKED,
            guards=(_FARMLAND_VERIFIED,),
            action=_run_redline_machine,
            description_zh="农田通过 → 运行生态保护红线子机",
        ),
        # ── 第二优先：生态保护红线 ──
        Transition(
            name="reject_ecological_redline",
            from_state=ThreeLinesState.REDLINE_CHECKED,
            to_state=ThreeLinesState.REJECTED_ECOLOGICAL_REDLINE,
            guards=(_REDLINE_REJECTED,),
            description_zh="地块重叠生态保护红线 → 拒绝",
        ),
        Transition(
            name="redline_fail_closed",
            from_state=ThreeLinesState.REDLINE_CHECKED,
            to_state=ThreeLinesState.FAIL_CLOSED,
            guards=(_REDLINE_FAIL_CLOSED,),
            description_zh="生态保护红线子机未决 → fail-closed 传染",
        ),
        Transition(
            name="redline_verified_next",
            from_state=ThreeLinesState.REDLINE_CHECKED,
            to_state=ThreeLinesState.BOUNDARY_CHECKED,
            guards=(_REDLINE_VERIFIED,),
            action=_run_boundary_machine,
            description_zh="红线通过 → 运行城镇开发边界子机",
        ),
        # ── 第三优先：城镇开发边界 ──
        Transition(
            name="reject_outside_boundary",
            from_state=ThreeLinesState.BOUNDARY_CHECKED,
            to_state=ThreeLinesState.REJECTED_OUTSIDE_BOUNDARY,
            guards=(_BOUNDARY_REJECTED,),
            description_zh="地块超出城镇开发边界 → 拒绝",
        ),
        Transition(
            name="boundary_fail_closed",
            from_state=ThreeLinesState.BOUNDARY_CHECKED,
            to_state=ThreeLinesState.FAIL_CLOSED,
            guards=(_BOUNDARY_FAIL_CLOSED,),
            description_zh="城镇开发边界子机未决 → fail-closed 传染",
        ),
        Transition(
            name="three_lines_all_verified",
            from_state=ThreeLinesState.BOUNDARY_CHECKED,
            to_state=ThreeLinesState.ALLOWED,
            guards=(_BOUNDARY_VERIFIED,),
            description_zh="三线全部通过 → 地块可建设（三线维度）",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 模块级入口（便捷用法）
# ═══════════════════════════════════════════════════════════════════

THREE_LINES_ORCHESTRATOR = ThreeLinesOrchestrator()


def judge_three_lines(parcel: Parcel, boundaries: ThreeLinesBoundaries) -> MachineRun[ThreeLinesState]:
    """一条调用完成三线综合判定：地块 + 三线边界 → 确定性结论。

    返回 MachineRun[ThreeLinesState]，含完整步迹、证据链与违规详情；
    completed=False 一律视为拒绝（fail-closed）。
    """
    ctx = JudgementContext(parcel=parcel, boundaries=boundaries)
    return THREE_LINES_ORCHESTRATOR.run(ctx)
