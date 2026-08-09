"""land_use_validator.py — 组合机：地块 → 三线判定 → 三区判定 → 建设许可结论。

Domain source: notes/01-territorial-spatial-planning.md §三区三线·对城市设计的约束

判定链（确定性，零 LLM）：
  1. 三线编排器：越线是硬约束 —— 任何三线违规（含 fail-closed）直接拒绝，
     不再评估三区。
  2. 三区编排器（仅三线全过后运行）：主导功能为生态空间或农业空间 → 拒绝
     （涉及生态/农业空间的建设活动只能作为生态保护和风貌协调，不得变更为
     建设用地）；主导功能为城镇空间 → 允许。

组合方式：复用 ZoneJudgementContext（继承 JudgementContext），不新建
context 类。两个编排器的 run() 已把结论自动写入 context（three_lines_verdict
/ three_zones_verdict），组合机的 action 只负责调用、guard 只负责读取。

输出：LandUseVerdict —— 组合机 MachineRun + 两个子机 MachineRun 的聚合
视图，全链证据（三线子机 + 三区子机 + 组合机）一次取齐。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .state_machine import (
    Evidence,
    EvidenceOutcome,
    Guard,
    GuardResult,
    MachineRun,
    Regulation,
    StateMachine,
    Transition,
    _fail_closed_evidence,
)
from .three_lines import (
    REG_URBAN_BOUNDARY,
    Parcel,
    ThreeLinesBoundaries,
    ThreeLinesOrchestrator,
    ThreeLinesState,
)
from .three_zones import (
    REG_AGRICULTURAL_ZONE,
    REG_ECOLOGICAL_ZONE,
    REG_URBAN_ZONE,
    ThreeZonesOrchestrator,
    ThreeZonesRegions,
    ThreeZonesState,
    ZoneJudgementContext,
)

# ═══════════════════════════════════════════════════════════════════
# 条款常量 —— 强制 evidence 的来源（固定中文文案，非生成文本）
# Source: notes/01-territorial-spatial-planning.md §三区三线·对城市设计的约束
# ═══════════════════════════════════════════════════════════════════

REG_ZONE_BUILDING_BAN = Regulation(
    doc_short="中发〔2019〕18号",
    doc_title_zh="关于建立国土空间规划体系并监督实施的若干意见",
    article_zh="三区三线·用途管制",
    rule_zh=(
        "生态空间、农业空间以生态与农业功能为主体功能；涉及生态空间和"
        "农业空间的建设活动只能作为生态保护和风貌协调，不得变更为建设用地"
    ),
)

# 三线判定拒绝的终态集合（任一命中 → 建设许可直接拒绝，无需三区判定）
_LINE_REJECT_STATES = frozenset({
    ThreeLinesState.REJECTED_BASIC_FARMLAND,
    ThreeLinesState.REJECTED_ECOLOGICAL_REDLINE,
    ThreeLinesState.REJECTED_OUTSIDE_BOUNDARY,
})


# ═══════════════════════════════════════════════════════════════════
# 状态枚举
# ═══════════════════════════════════════════════════════════════════

class LandUseState(Enum):
    PENDING = "pending"
    LINES_CHECKED = "lines_checked"
    ZONES_CHECKED = "zones_checked"
    BUILDING_ALLOWED = "building_allowed"   # 城镇空间 + 三线全过 → 允许建设
    DENIED_BY_LINE = "denied_by_line"       # 三线违规（原因见上浮证据/子机 verdict）
    DENIED_BY_ZONE = "denied_by_zone"       # 生态/农业空间 → 不得变更为建设用地
    FAIL_CLOSED = "fail_closed"             # 任一子机未决 → 传染拒绝


# ═══════════════════════════════════════════════════════════════════
# 三线结论 guard（LINES_CHECKED 状态分支）
# ═══════════════════════════════════════════════════════════════════

def _check_lines_rejected(ctx: ZoneJudgementContext) -> GuardResult:
    verdict = ctx.three_lines_verdict
    if verdict is None:
        return GuardResult.fail(_fail_closed_evidence(
            "lines_rejected", "三线编排器未运行，无法判定，按 fail-closed 拒绝"))
    if not verdict.completed:
        # 三线未决 → 交给 lines_fail_closed 转换
        return GuardResult.fail(Evidence(
            rule_id="lines_rejected", outcome=EvidenceOutcome.COMPLIANT,
            regulation=REG_URBAN_BOUNDARY, detail="三线判定未决", metric=()))
    if verdict.final_state in _LINE_REJECT_STATES:
        # 确认"三线拒绝"事实 → 触发拒绝转换；违规证据直接上浮（条款+面积完整）
        return GuardResult.ok(*verdict.violations)
    return GuardResult.fail(Evidence(
        rule_id="lines_rejected", outcome=EvidenceOutcome.COMPLIANT,
        regulation=REG_URBAN_BOUNDARY, detail="三线判定未拒绝", metric=()))


_LINES_REJECTED_GUARD = Guard(
    guard_id="lines_rejected",
    regulations=(REG_URBAN_BOUNDARY,),
    check=_check_lines_rejected,
    description_zh="三线判定拒绝 → 建设许可直接拒绝（越线是硬约束）",
)


def _check_lines_fail_closed(ctx: ZoneJudgementContext) -> GuardResult:
    verdict = ctx.three_lines_verdict
    if verdict is None:
        return GuardResult.fail(_fail_closed_evidence(
            "lines_fail_closed", "三线编排器未运行，无法判定，按 fail-closed 拒绝"))
    if not verdict.completed:
        # 确认"三线未决"事实 → fail-closed 传染
        return GuardResult.ok(_fail_closed_evidence(
            "lines_fail_closed", "三线判定未决（数据缺失/异常），建设许可按 fail-closed 拒绝"))
    return GuardResult.fail(Evidence(
        rule_id="lines_fail_closed", outcome=EvidenceOutcome.COMPLIANT,
        regulation=REG_URBAN_BOUNDARY, detail="三线已得出确定结论", metric=()))


_LINES_FAIL_CLOSED_GUARD = Guard(
    guard_id="lines_fail_closed",
    regulations=(REG_URBAN_BOUNDARY,),
    check=_check_lines_fail_closed,
    description_zh="三线未决 → fail-closed 传染",
)


def _check_lines_allowed(ctx: ZoneJudgementContext) -> GuardResult:
    verdict = ctx.three_lines_verdict
    if verdict is None:
        return GuardResult.fail(_fail_closed_evidence(
            "lines_allowed", "三线编排器未运行，无法判定，按 fail-closed 拒绝"))
    if not verdict.completed:
        # 三线未决 → 交给 lines_fail_closed 转换
        return GuardResult.fail(Evidence(
            rule_id="lines_allowed", outcome=EvidenceOutcome.COMPLIANT,
            regulation=REG_URBAN_BOUNDARY, detail="三线判定未决", metric=()))
    if verdict.final_state is ThreeLinesState.ALLOWED:
        # 确认"三线全过"事实 → 进入三区判定
        return GuardResult.ok(Evidence(
            rule_id="lines_allowed", outcome=EvidenceOutcome.COMPLIANT,
            regulation=REG_URBAN_BOUNDARY,
            detail="三线判定通过：地块不触红线/农田且全部位于城镇开发边界内", metric=()))
    return GuardResult.fail(Evidence(
        rule_id="lines_allowed", outcome=EvidenceOutcome.VIOLATION,
        regulation=REG_URBAN_BOUNDARY, detail="三线判定拒绝", metric=()))


_LINES_ALLOWED_GUARD = Guard(
    guard_id="lines_allowed",
    regulations=(REG_URBAN_BOUNDARY,),
    check=_check_lines_allowed,
    description_zh="三线判定通过 → 进入三区主导功能判定",
)


# ═══════════════════════════════════════════════════════════════════
# 三区结论 guard（ZONES_CHECKED 状态分支）
# ═══════════════════════════════════════════════════════════════════

def _zone_ratio_metrics(ctx: ZoneJudgementContext) -> tuple[tuple[str, float], ...]:
    return (
        ("ecological_ratio", ctx.ecological_overlap_ratio or 0.0),
        ("agricultural_ratio", ctx.agricultural_overlap_ratio or 0.0),
        ("urban_ratio", ctx.urban_overlap_ratio or 0.0),
    )


def _make_zone_verdict_guard(
    *,
    guard_id: str,
    zone_state: ThreeZonesState,
    regulation: Regulation,
    detail_pass: str,
    detail_fail: str,
) -> Guard[ZoneJudgementContext]:
    """生成"三区主导功能为 X"的确认 guard（几何事实，无优先级）。"""
    def check(ctx: ZoneJudgementContext) -> GuardResult:
        verdict = ctx.three_zones_verdict
        if verdict is None:
            return GuardResult.fail(_fail_closed_evidence(
                guard_id, "三区编排器未运行，无法判定，按 fail-closed 拒绝"))
        if not verdict.completed:
            # 三区未决 → 交给 zones_fail_closed 转换
            return GuardResult.fail(Evidence(
                rule_id=guard_id, outcome=EvidenceOutcome.COMPLIANT,
                regulation=regulation, detail="三区判定未决", metric=()))
        if verdict.final_state is zone_state:
            # 确认"主导功能为 X"事实 → 触发对应转换
            return GuardResult.ok(Evidence(
                rule_id=guard_id, outcome=EvidenceOutcome.COMPLIANT,
                regulation=regulation, detail=detail_pass,
                metric=_zone_ratio_metrics(ctx)))
        return GuardResult.fail(Evidence(
            rule_id=guard_id, outcome=EvidenceOutcome.COMPLIANT,
            regulation=regulation, detail=detail_fail, metric=()))

    return Guard(guard_id=guard_id, regulations=(regulation,),
                 check=check, description_zh=detail_pass)


_ZONES_ECOLOGICAL_GUARD = _make_zone_verdict_guard(
    guard_id="zones_dominant_ecological",
    zone_state=ThreeZonesState.ECOLOGICAL,
    regulation=REG_ECOLOGICAL_ZONE,
    detail_pass="地块主导功能为生态空间",
    detail_fail="地块主导功能不是生态空间",
)

_ZONES_AGRICULTURAL_GUARD = _make_zone_verdict_guard(
    guard_id="zones_dominant_agricultural",
    zone_state=ThreeZonesState.AGRICULTURAL,
    regulation=REG_AGRICULTURAL_ZONE,
    detail_pass="地块主导功能为农业空间",
    detail_fail="地块主导功能不是农业空间",
)

_ZONES_URBAN_GUARD = _make_zone_verdict_guard(
    guard_id="zones_dominant_urban",
    zone_state=ThreeZonesState.URBAN,
    regulation=REG_URBAN_ZONE,
    detail_pass="地块主导功能为城镇空间",
    detail_fail="地块主导功能不是城镇空间",
)


def _check_zones_fail_closed(ctx: ZoneJudgementContext) -> GuardResult:
    verdict = ctx.three_zones_verdict
    if verdict is None:
        return GuardResult.fail(_fail_closed_evidence(
            "zones_fail_closed", "三区编排器未运行，无法判定，按 fail-closed 拒绝"))
    if not verdict.completed:
        # 确认"三区未决"事实 → fail-closed 传染
        return GuardResult.ok(_fail_closed_evidence(
            "zones_fail_closed", "三区判定未决（占比并列/全零/数据缺失），建设许可按 fail-closed 拒绝"))
    return GuardResult.fail(Evidence(
        rule_id="zones_fail_closed", outcome=EvidenceOutcome.COMPLIANT,
        regulation=REG_URBAN_BOUNDARY, detail="三区已得出确定结论", metric=()))


_ZONES_FAIL_CLOSED_GUARD = Guard(
    guard_id="zones_fail_closed",
    regulations=(REG_URBAN_BOUNDARY,),
    check=_check_zones_fail_closed,
    description_zh="三区未决 → fail-closed 传染",
)


def _check_zone_building_ban(ctx: ZoneJudgementContext) -> GuardResult:
    """生态/农业空间 → 不得变更为建设用地（拒绝事实确认，证据引用用途管制条款）。"""
    verdict = ctx.three_zones_verdict
    if verdict is None:
        return GuardResult.fail(_fail_closed_evidence(
            "zone_building_ban", "三区编排器未运行，无法判定，按 fail-closed 拒绝"))
    if not verdict.completed:
        return GuardResult.fail(Evidence(
            rule_id="zone_building_ban", outcome=EvidenceOutcome.COMPLIANT,
            regulation=REG_ZONE_BUILDING_BAN, detail="三区判定未决", metric=()))
    if verdict.final_state in (ThreeZonesState.ECOLOGICAL, ThreeZonesState.AGRICULTURAL):
        zone_label = "生态空间" if verdict.final_state is ThreeZonesState.ECOLOGICAL else "农业空间"
        return GuardResult.ok(Evidence(
            rule_id="zone_building_ban",
            outcome=EvidenceOutcome.VIOLATION,
            regulation=REG_ZONE_BUILDING_BAN,
            detail=f"地块主导功能为{zone_label}，不得变更为建设用地（只能作为生态保护和风貌协调）",
            metric=_zone_ratio_metrics(ctx),
        ))
    return GuardResult.fail(Evidence(
        rule_id="zone_building_ban", outcome=EvidenceOutcome.COMPLIANT,
        regulation=REG_ZONE_BUILDING_BAN, detail="地块主导功能为城镇空间，不受用途管制禁令", metric=()))


_ZONE_BUILDING_BAN_GUARD = Guard(
    guard_id="zone_building_ban",
    regulations=(REG_ZONE_BUILDING_BAN,),
    check=_check_zone_building_ban,
    description_zh="生态/农业空间不得变更为建设用地",
)


# ═══════════════════════════════════════════════════════════════════
# 编排器 action：调用子机编排器（结论自动入册，guard 只读）
# ═══════════════════════════════════════════════════════════════════

_THREE_LINES_ORCHESTRATOR = ThreeLinesOrchestrator()
_THREE_ZONES_ORCHESTRATOR = ThreeZonesOrchestrator()


def _run_three_lines_orchestrator(ctx: ZoneJudgementContext) -> None:
    _THREE_LINES_ORCHESTRATOR.run(ctx)  # 结论自动入册 ctx.three_lines_verdict


def _run_three_zones_orchestrator(ctx: ZoneJudgementContext) -> None:
    _THREE_ZONES_ORCHESTRATOR.run(ctx)  # 结论自动入册 ctx.three_zones_verdict


# ═══════════════════════════════════════════════════════════════════
# 组合机
# ═══════════════════════════════════════════════════════════════════

class LandUseOrchestrator(StateMachine[LandUseState, ZoneJudgementContext]):
    """建设许可组合机：地块 → 三线 → 三区 → 建设许可结论。

    硬约束优先：三线拒绝/未决即终（三区不评估）；三线全过后，
    三区主导功能决定许可结论（生态/农业 → 拒绝，城镇 → 允许）。
    """
    machine_id = "land_use_validator"
    state_enum = LandUseState
    initial_state = LandUseState.PENDING

    def run(self, ctx: ZoneJudgementContext) -> "LandUseVerdict":
        """运行组合机，FAIL_CLOSED 归一为 completed=False，并组装全链证据聚合视图。"""
        run = super().run(ctx)
        if run.final_state is LandUseState.FAIL_CLOSED and run.completed:
            run = MachineRun(
                machine_id=self.machine_id, completed=False,
                final_state=run.final_state, steps=run.steps,
            )
        return LandUseVerdict(
            run=run,
            three_lines=ctx.three_lines_verdict,
            three_zones=ctx.three_zones_verdict,
        )

    transitions: tuple[Transition[LandUseState, ZoneJudgementContext], ...] = (
        # ── 第一层：三线（越线是硬约束）──
        Transition(
            name="check_three_lines",
            from_state=LandUseState.PENDING,
            to_state=LandUseState.LINES_CHECKED,
            action=_run_three_lines_orchestrator,
            description_zh="运行三线编排器（农田 > 红线 > 边界）",
        ),
        Transition(
            name="deny_by_line",
            from_state=LandUseState.LINES_CHECKED,
            to_state=LandUseState.DENIED_BY_LINE,
            guards=(_LINES_REJECTED_GUARD,),
            description_zh="三线违规 → 建设许可直接拒绝",
        ),
        Transition(
            name="lines_fail_closed",
            from_state=LandUseState.LINES_CHECKED,
            to_state=LandUseState.FAIL_CLOSED,
            guards=(_LINES_FAIL_CLOSED_GUARD,),
            description_zh="三线未决 → fail-closed 传染",
        ),
        Transition(
            name="check_three_zones",
            from_state=LandUseState.LINES_CHECKED,
            to_state=LandUseState.ZONES_CHECKED,
            guards=(_LINES_ALLOWED_GUARD,),
            action=_run_three_zones_orchestrator,
            description_zh="三线全过 → 运行三区编排器（主导功能分类）",
        ),
        # ── 第二层：三区主导功能（无优先级，几何事实）──
        Transition(
            name="deny_by_ecological_zone",
            from_state=LandUseState.ZONES_CHECKED,
            to_state=LandUseState.DENIED_BY_ZONE,
            guards=(_ZONES_ECOLOGICAL_GUARD, _ZONE_BUILDING_BAN_GUARD),
            description_zh="主导功能为生态空间 → 不得变更为建设用地",
        ),
        Transition(
            name="deny_by_agricultural_zone",
            from_state=LandUseState.ZONES_CHECKED,
            to_state=LandUseState.DENIED_BY_ZONE,
            guards=(_ZONES_AGRICULTURAL_GUARD, _ZONE_BUILDING_BAN_GUARD),
            description_zh="主导功能为农业空间 → 不得变更为建设用地",
        ),
        Transition(
            name="zones_fail_closed",
            from_state=LandUseState.ZONES_CHECKED,
            to_state=LandUseState.FAIL_CLOSED,
            guards=(_ZONES_FAIL_CLOSED_GUARD,),
            description_zh="三区未决 → fail-closed 传染",
        ),
        Transition(
            name="allow_building",
            from_state=LandUseState.ZONES_CHECKED,
            to_state=LandUseState.BUILDING_ALLOWED,
            guards=(_ZONES_URBAN_GUARD,),
            description_zh="城镇空间 + 三线全过 → 允许建设",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 输出类型 —— 建设许可结论 + 全链证据聚合视图
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LandUseVerdict:
    """建设许可判定结论。

    - run：组合机 MachineRun（状态链与组合机自身证据）
    - three_lines / three_zones：两个子机编排器 MachineRun（完整步迹）
    - evidences / violations：三层证据聚合（三线子机 + 三区子机 + 组合机）
    - allowed：唯一通过条件 = 组合机完成且结论为 BUILDING_ALLOWED
    """
    run: MachineRun[LandUseState]
    three_lines: MachineRun[ThreeLinesState] | None
    three_zones: MachineRun[ThreeZonesState] | None

    @property
    def allowed(self) -> bool:
        return self.run.completed and self.run.final_state is LandUseState.BUILDING_ALLOWED

    @property
    def denied(self) -> bool:
        return self.run.completed and self.run.final_state in (
            LandUseState.DENIED_BY_LINE,
            LandUseState.DENIED_BY_ZONE,
        )

    @property
    def evidences(self) -> tuple[Evidence, ...]:
        """全链证据：组合机 + 三线编排器 + 三区编排器。"""
        return (
            self.run.evidences
            + (self.three_lines.evidences if self.three_lines else ())
            + (self.three_zones.evidences if self.three_zones else ())
        )

    @property
    def violations(self) -> tuple[Evidence, ...]:
        return tuple(e for e in self.evidences if e.outcome is EvidenceOutcome.VIOLATION)


# ═══════════════════════════════════════════════════════════════════
# 模块级入口（便捷用法）
# ═══════════════════════════════════════════════════════════════════

LAND_USE_ORCHESTRATOR = LandUseOrchestrator()


def judge_land_use(
    parcel: Parcel,
    boundaries: ThreeLinesBoundaries,
    regions: ThreeZonesRegions,
) -> LandUseVerdict:
    """一条调用完成建设许可判定：地块 + 三线边界 + 三区边界 → 结论。

    组合机内部自动运行三线编排器与三区编排器，三层证据全部聚合在
    返回的 LandUseVerdict 中；allowed=False 一律视为不可建设（含拒绝与未决）。
    """
    ctx = ZoneJudgementContext(parcel=parcel, boundaries=boundaries, zones=regions)
    return LAND_USE_ORCHESTRATOR.run(ctx)
