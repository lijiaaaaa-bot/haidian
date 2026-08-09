"""three_zones.py — "三区"判定子机与编排器。

Domain source: notes/01-territorial-spatial-planning.md §三区三线

与三线的本质区别：
  - 三线 = 边界刚性管控："该地块是否越线"（重叠存在性判定）
  - 三区 = 主导功能划分："该地块属于哪个空间"（重叠面积占比分类）

判定规则（确定性，零 LLM）：
  - 每个空间子机测量地块与该空间的 重叠面积占比 = 重叠面积 / 地块面积，
    并给出从属判定（占比 > 0 即从属该空间）。
  - 编排器对三个占比做主导分类：占比唯一最大者胜。
  - 占比并列（差 ≤ DOMINANCE_EPSILON）或地块与所有空间均无重叠
    → fail-closed（不猜）。
  - 任何测量不完整（地块无效 / 区域数据缺失 / 退化地块）
    → fail-closed（不确定即拒）。

刻意不做的事：
  - 三区没有法定优先级（与三线的 农田 > 红线 > 边界 不同）。三个分类
    guard 是几何事实的互斥分支，声明顺序与结果无关——没有"城镇优先"
    之类的隐性规则编码。
  - 三区数据不做"互不重叠"硬校验（主导功能分区允许边界过渡），只依赖
    面积占比的确定性比较。

组合：ZoneJudgementContext 继承 JudgementContext（三线工作簿），三区
编排器结论经 record_three_zones_verdict 入册，与 three_lines_verdict
一起供 land_use_validator.py 读取。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal, cast

from shapely import Geometry

from .state_machine import (
    SYSTEM_FAIL_CLOSED,
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
    AREA_EPSILON,
    JudgementContext,
    Parcel,
    ThreeLinesBoundaries,
)

# ═══════════════════════════════════════════════════════════════════
# 条款常量 —— 强制 evidence 的来源（固定中文文案，非生成文本）
# Source: notes/01-territorial-spatial-planning.md §三区三线
# ═══════════════════════════════════════════════════════════════════

REG_THREE_ZONES = Regulation(
    doc_short="中发〔2019〕18号",
    doc_title_zh="关于建立国土空间规划体系并监督实施的若干意见",
    article_zh="三区三线",
    rule_zh="生态空间、农业空间、城镇空间按主导功能划分国土空间",
)

REG_ECOLOGICAL_ZONE = Regulation(
    doc_short="中发〔2019〕18号",
    doc_title_zh="关于建立国土空间规划体系并监督实施的若干意见",
    article_zh="三区三线·生态空间",
    rule_zh="以提供生态服务或生态产品为主体功能的区域",
)

REG_AGRICULTURAL_ZONE = Regulation(
    doc_short="中发〔2019〕18号",
    doc_title_zh="关于建立国土空间规划体系并监督实施的若干意见",
    article_zh="三区三线·农业空间",
    rule_zh="以农业生产和农村居民生活为主体功能的区域",
)

REG_URBAN_ZONE = Regulation(
    doc_short="中发〔2019〕18号",
    doc_title_zh="关于建立国土空间规划体系并监督实施的若干意见",
    article_zh="三区三线·城镇空间",
    rule_zh="以城镇居民生产生活为主体功能的区域",
)

# 主导功能占比并列容差（占比为 [0,1] 无量纲值）。
# 最大占比与次大占比之差 ≤ DOMINANCE_EPSILON 视为并列 → fail-closed。
DOMINANCE_EPSILON = 1e-9


# ═══════════════════════════════════════════════════════════════════
# 输入类型
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ThreeZonesRegions:
    """三类空间的功能分区边界。任一字段为 None 表示该区数据缺失。

    数据允许过渡重叠（主导功能分区边界模糊是常态），但判定只依据
    面积占比的确定性比较。
    """
    ecological_zone: Geometry | None = None     # 生态空间
    agricultural_zone: Geometry | None = None   # 农业空间
    urban_zone: Geometry | None = None          # 城镇空间


# ═══════════════════════════════════════════════════════════════════
# ZoneJudgementContext —— 三区共享工作簿（继承三线工作簿）
# ═══════════════════════════════════════════════════════════════════

@dataclass(kw_only=True)
class ZoneJudgementContext(JudgementContext):
    """三区判定共享上下文。

    - zones：三区输入（子机与编排器只读）
    - *_overlap_ratio：子机 measure action 预计算的占比（类型化字段）
    - *_zone_run：子机结果，经 record_* 写入 results dict（类型化 property）
    - three_zones_verdict：编排器结论入册，与 three_lines_verdict 一同
      供 land_use_validator.py 读取
    """
    zones: ThreeZonesRegions

    # 几何预计算（measure action 写入；None = 无法测量）
    ecological_overlap_ratio: float | None = None
    agricultural_overlap_ratio: float | None = None
    urban_overlap_ratio: float | None = None

    # results dict 内部键
    KEY_ECOLOGICAL_ZONE_RUN = "run.ecological_zone"
    KEY_AGRICULTURAL_ZONE_RUN = "run.agricultural_zone"
    KEY_URBAN_ZONE_RUN = "run.urban_zone"
    KEY_THREE_ZONES_VERDICT = "verdict.three_zones"  # 编排器结论（供组合机读取）

    @property
    def ecological_zone_run(self) -> MachineRun["EcologicalZoneState"] | None:
        return cast("MachineRun[EcologicalZoneState] | None", self.results.get(self.KEY_ECOLOGICAL_ZONE_RUN))

    @property
    def agricultural_zone_run(self) -> MachineRun["AgriculturalZoneState"] | None:
        return cast("MachineRun[AgriculturalZoneState] | None", self.results.get(self.KEY_AGRICULTURAL_ZONE_RUN))

    @property
    def urban_zone_run(self) -> MachineRun["UrbanZoneState"] | None:
        return cast("MachineRun[UrbanZoneState] | None", self.results.get(self.KEY_URBAN_ZONE_RUN))

    def record_ecological_zone_run(self, run: MachineRun["EcologicalZoneState"]) -> None:
        self.results[self.KEY_ECOLOGICAL_ZONE_RUN] = run

    def record_agricultural_zone_run(self, run: MachineRun["AgriculturalZoneState"]) -> None:
        self.results[self.KEY_AGRICULTURAL_ZONE_RUN] = run

    def record_urban_zone_run(self, run: MachineRun["UrbanZoneState"]) -> None:
        self.results[self.KEY_URBAN_ZONE_RUN] = run

    # ── 编排器结论入册（ThreeZonesOrchestrator.run 自动写入）──
    @property
    def three_zones_verdict(self) -> MachineRun["ThreeZonesState"] | None:
        return cast("MachineRun[ThreeZonesState] | None", self.results.get(self.KEY_THREE_ZONES_VERDICT))

    def record_three_zones_verdict(self, run: MachineRun["ThreeZonesState"]) -> None:
        self.results[self.KEY_THREE_ZONES_VERDICT] = run


# ═══════════════════════════════════════════════════════════════════
# 几何判定辅助
# ═══════════════════════════════════════════════════════════════════

def _zone_ratio(parcel_geom: Geometry | None, zone_geom: Geometry | None) -> float | None:
    """地块与该空间的重叠面积占比（0~1）；无法测量 → None。

    None 的三种情况：地块几何缺失 / 区域数据缺失 / 地块面积退化为零。
    """
    if parcel_geom is None or zone_geom is None:
        return None
    parcel_area = parcel_geom.area
    if parcel_area <= AREA_EPSILON:
        return None
    return parcel_geom.intersection(zone_geom).area / parcel_area


def _ratio_metrics(ctx: ZoneJudgementContext) -> tuple[tuple[str, float], ...]:
    """三个占比的确定性量化依据（None 按 0 计，供证据 metric 展示）。"""
    return (
        ("ecological_ratio", ctx.ecological_overlap_ratio or 0.0),
        ("agricultural_ratio", ctx.agricultural_overlap_ratio or 0.0),
        ("urban_ratio", ctx.urban_overlap_ratio or 0.0),
    )


def _all_ratios_measured(ctx: ZoneJudgementContext) -> bool:
    return all(
        r is not None
        for r in (ctx.ecological_overlap_ratio, ctx.agricultural_overlap_ratio, ctx.urban_overlap_ratio)
    )


def _dominant_zone(ctx: ZoneJudgementContext) -> str | None | Literal["TIE"]:
    """主导空间判定：占比唯一最大者的键；测量不完整 → None；并列/全零 → "TIE"。"""
    ratios = {
        "ecological": ctx.ecological_overlap_ratio,
        "agricultural": ctx.agricultural_overlap_ratio,
        "urban": ctx.urban_overlap_ratio,
    }
    if any(v is None for v in ratios.values()):
        return None
    values = sorted(ratios.values(), reverse=True)
    if values[0] - values[1] <= DOMINANCE_EPSILON:
        return "TIE"
    return max(ratios, key=ratios.get)  # type: ignore[arg-type] — values 已全非 None


# ═══════════════════════════════════════════════════════════════════
# Guard 工厂 —— 子机"从属判定" guard（先 measure 后判定）
# ═══════════════════════════════════════════════════════════════════

def _make_zone_guards(
    *,
    guard_prefix: str,
    regulation: Regulation,
    zone_label: str,
    get_ratio: Callable[[ZoneJudgementContext], float | None],
) -> tuple[Guard[ZoneJudgementContext], Guard[ZoneJudgementContext]]:
    """生成一对互补 guard：(overlaps 从属, disjoint 无从属)。

    两者必居其一；测量不完整（ratio=None）时两者都 fail → 子机 fail-closed。
    """
    overlaps_id = f"{guard_prefix}_overlaps"
    disjoint_id = f"{guard_prefix}_disjoint"

    def check_overlaps(ctx: ZoneJudgementContext) -> GuardResult:
        ratio = get_ratio(ctx)
        if ratio is None:
            return GuardResult.fail(_fail_closed_evidence(
                overlaps_id, f"无法测量地块与{zone_label}的重叠占比（地块无效或区域数据缺失），按 fail-closed 拒绝"))
        if ratio > AREA_EPSILON:
            # 确认"地块从属该空间"事实 → 触发 OVERLAPS 转换
            return GuardResult.ok(Evidence(
                rule_id=overlaps_id, outcome=EvidenceOutcome.COMPLIANT,
                regulation=regulation, detail=f"地块与{zone_label}存在重叠（从属该空间）",
                metric=((f"{guard_prefix}_ratio", ratio),)))
        return GuardResult.fail(Evidence(
            rule_id=overlaps_id, outcome=EvidenceOutcome.COMPLIANT,
            regulation=regulation, detail=f"地块与{zone_label}无重叠", metric=()))

    def check_disjoint(ctx: ZoneJudgementContext) -> GuardResult:
        ratio = get_ratio(ctx)
        if ratio is None:
            return GuardResult.fail(_fail_closed_evidence(
                disjoint_id, f"无法测量地块与{zone_label}的重叠占比（地块无效或区域数据缺失），按 fail-closed 拒绝"))
        if ratio <= AREA_EPSILON:
            # 确认"地块无从属"事实 → 触发 DISJOINT 转换
            return GuardResult.ok(Evidence(
                rule_id=disjoint_id, outcome=EvidenceOutcome.COMPLIANT,
                regulation=regulation, detail=f"地块与{zone_label}无重叠",
                metric=((f"{guard_prefix}_ratio", ratio),)))
        return GuardResult.fail(Evidence(
            rule_id=disjoint_id, outcome=EvidenceOutcome.COMPLIANT,
            regulation=regulation, detail=f"地块与{zone_label}存在重叠", metric=()))

    return (
        Guard(guard_id=overlaps_id, regulations=(regulation,),
              check=check_overlaps, description_zh=f"地块从属{zone_label}"),
        Guard(guard_id=disjoint_id, regulations=(regulation,),
              check=check_disjoint, description_zh=f"地块不从属{zone_label}"),
    )


# ═══════════════════════════════════════════════════════════════════
# 子机一：生态空间
# Source: 中发〔2019〕18号 —— 生态空间以提供生态服务或生态产品为主体功能
# ═══════════════════════════════════════════════════════════════════

class EcologicalZoneState(Enum):
    PENDING = "pending"
    MEASURED = "measured"
    OVERLAPS = "overlaps"    # 从属该空间
    DISJOINT = "disjoint"    # 无从属
    FAIL_CLOSED = "fail_closed"


def _measure_ecological(ctx: ZoneJudgementContext) -> None:
    """action：预计算地块与生态空间的重叠面积占比。"""
    ctx.ecological_overlap_ratio = _zone_ratio(ctx.parcel.geometry, ctx.zones.ecological_zone)


_ECOLOGICAL_OVERLAPS_GUARD, _ECOLOGICAL_DISJOINT_GUARD = _make_zone_guards(
    guard_prefix="ecological",
    regulation=REG_ECOLOGICAL_ZONE,
    zone_label="生态空间",
    get_ratio=lambda ctx: ctx.ecological_overlap_ratio,
)


class EcologicalZoneMachine(StateMachine[EcologicalZoneState, ZoneJudgementContext]):
    """生态空间从属判定子机（可独立运行）。"""
    machine_id = "ecological_zone"
    state_enum = EcologicalZoneState
    initial_state = EcologicalZoneState.PENDING
    fail_closed_state = EcologicalZoneState.FAIL_CLOSED

    transitions: tuple[Transition[EcologicalZoneState, ZoneJudgementContext], ...] = (
        Transition(
            name="measure_ecological_zone",
            from_state=EcologicalZoneState.PENDING,
            to_state=EcologicalZoneState.MEASURED,
            action=_measure_ecological,
            description_zh="计算地块与生态空间的重叠面积占比",
        ),
        Transition(
            name="ecological_zone_overlaps",
            from_state=EcologicalZoneState.MEASURED,
            to_state=EcologicalZoneState.OVERLAPS,
            guards=(_ECOLOGICAL_OVERLAPS_GUARD,),
            description_zh="地块从属生态空间",
        ),
        Transition(
            name="ecological_zone_disjoint",
            from_state=EcologicalZoneState.MEASURED,
            to_state=EcologicalZoneState.DISJOINT,
            guards=(_ECOLOGICAL_DISJOINT_GUARD,),
            description_zh="地块不从属生态空间",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 子机二：农业空间
# Source: 中发〔2019〕18号 —— 农业空间以农业生产和农村居民生活为主体功能
# ═══════════════════════════════════════════════════════════════════

class AgriculturalZoneState(Enum):
    PENDING = "pending"
    MEASURED = "measured"
    OVERLAPS = "overlaps"
    DISJOINT = "disjoint"
    FAIL_CLOSED = "fail_closed"


def _measure_agricultural(ctx: ZoneJudgementContext) -> None:
    """action：预计算地块与农业空间的重叠面积占比。"""
    ctx.agricultural_overlap_ratio = _zone_ratio(ctx.parcel.geometry, ctx.zones.agricultural_zone)


_AGRICULTURAL_OVERLAPS_GUARD, _AGRICULTURAL_DISJOINT_GUARD = _make_zone_guards(
    guard_prefix="agricultural",
    regulation=REG_AGRICULTURAL_ZONE,
    zone_label="农业空间",
    get_ratio=lambda ctx: ctx.agricultural_overlap_ratio,
)


class AgriculturalZoneMachine(StateMachine[AgriculturalZoneState, ZoneJudgementContext]):
    """农业空间从属判定子机（可独立运行）。"""
    machine_id = "agricultural_zone"
    state_enum = AgriculturalZoneState
    initial_state = AgriculturalZoneState.PENDING
    fail_closed_state = AgriculturalZoneState.FAIL_CLOSED

    transitions: tuple[Transition[AgriculturalZoneState, ZoneJudgementContext], ...] = (
        Transition(
            name="measure_agricultural_zone",
            from_state=AgriculturalZoneState.PENDING,
            to_state=AgriculturalZoneState.MEASURED,
            action=_measure_agricultural,
            description_zh="计算地块与农业空间的重叠面积占比",
        ),
        Transition(
            name="agricultural_zone_overlaps",
            from_state=AgriculturalZoneState.MEASURED,
            to_state=AgriculturalZoneState.OVERLAPS,
            guards=(_AGRICULTURAL_OVERLAPS_GUARD,),
            description_zh="地块从属农业空间",
        ),
        Transition(
            name="agricultural_zone_disjoint",
            from_state=AgriculturalZoneState.MEASURED,
            to_state=AgriculturalZoneState.DISJOINT,
            guards=(_AGRICULTURAL_DISJOINT_GUARD,),
            description_zh="地块不从属农业空间",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 子机三：城镇空间
# Source: 中发〔2019〕18号 —— 城镇空间以城镇居民生产生活为主体功能
# ═══════════════════════════════════════════════════════════════════

class UrbanZoneState(Enum):
    PENDING = "pending"
    MEASURED = "measured"
    OVERLAPS = "overlaps"
    DISJOINT = "disjoint"
    FAIL_CLOSED = "fail_closed"


def _measure_urban(ctx: ZoneJudgementContext) -> None:
    """action：预计算地块与城镇空间的重叠面积占比。"""
    ctx.urban_overlap_ratio = _zone_ratio(ctx.parcel.geometry, ctx.zones.urban_zone)


_URBAN_OVERLAPS_GUARD, _URBAN_DISJOINT_GUARD = _make_zone_guards(
    guard_prefix="urban",
    regulation=REG_URBAN_ZONE,
    zone_label="城镇空间",
    get_ratio=lambda ctx: ctx.urban_overlap_ratio,
)


class UrbanZoneMachine(StateMachine[UrbanZoneState, ZoneJudgementContext]):
    """城镇空间从属判定子机（可独立运行）。"""
    machine_id = "urban_zone"
    state_enum = UrbanZoneState
    initial_state = UrbanZoneState.PENDING
    fail_closed_state = UrbanZoneState.FAIL_CLOSED

    transitions: tuple[Transition[UrbanZoneState, ZoneJudgementContext], ...] = (
        Transition(
            name="measure_urban_zone",
            from_state=UrbanZoneState.PENDING,
            to_state=UrbanZoneState.MEASURED,
            action=_measure_urban,
            description_zh="计算地块与城镇空间的重叠面积占比",
        ),
        Transition(
            name="urban_zone_overlaps",
            from_state=UrbanZoneState.MEASURED,
            to_state=UrbanZoneState.OVERLAPS,
            guards=(_URBAN_OVERLAPS_GUARD,),
            description_zh="地块从属城镇空间",
        ),
        Transition(
            name="urban_zone_disjoint",
            from_state=UrbanZoneState.MEASURED,
            to_state=UrbanZoneState.DISJOINT,
            guards=(_URBAN_DISJOINT_GUARD,),
            description_zh="地块不从属城镇空间",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 编排器：ThreeZonesOrchestrator
# 分类由几何占比决定 —— 无优先级编码，并列即 fail-closed（不猜）
# ═══════════════════════════════════════════════════════════════════

class ThreeZonesState(Enum):
    PENDING = "pending"
    ZONES_MEASURED = "zones_measured"
    ECOLOGICAL = "ecological"          # 主导功能：生态空间
    AGRICULTURAL = "agricultural"      # 主导功能：农业空间
    URBAN = "urban"                    # 主导功能：城镇空间
    FAIL_CLOSED = "fail_closed"        # 测量不完整 / 并列 / 全零 → 不猜


def _run_all_zone_machines(ctx: ZoneJudgementContext) -> None:
    """action：顺序运行三个三区子机，结果入册。"""
    ctx.record_ecological_zone_run(_ECOLOGICAL_ZONE_MACHINE.run(ctx))
    ctx.record_agricultural_zone_run(_AGRICULTURAL_ZONE_MACHINE.run(ctx))
    ctx.record_urban_zone_run(_URBAN_ZONE_MACHINE.run(ctx))


# ── 测量完整性 guard ──

def _check_measurement_failed(ctx: ZoneJudgementContext) -> GuardResult:
    if not _all_ratios_measured(ctx):
        return GuardResult.ok(Evidence(
            rule_id="zone_measurement_failed",
            outcome=EvidenceOutcome.VIOLATION,
            regulation=SYSTEM_FAIL_CLOSED,
            detail="三区测量不完整（地块无效或区域数据缺失），无法判定主导功能，按 fail-closed 拒绝",
            metric=_ratio_metrics(ctx),
        ))
    return GuardResult.fail(Evidence(
        rule_id="zone_measurement_failed", outcome=EvidenceOutcome.COMPLIANT,
        regulation=SYSTEM_FAIL_CLOSED, detail="三区测量完整", metric=()))


_MEASUREMENT_FAILED_GUARD = Guard(
    guard_id="zone_measurement_failed",
    regulations=(SYSTEM_FAIL_CLOSED,),
    check=_check_measurement_failed,
    description_zh="三区测量完整性校验：不完整 → fail-closed",
)


# ── 主导功能 guard：唯一最大占比者胜；并列/全零 fail-closed ──

def _check_no_unique_dominant(ctx: ZoneJudgementContext) -> GuardResult:
    if not _all_ratios_measured(ctx):
        return GuardResult.fail(Evidence(
            rule_id="no_unique_dominant", outcome=EvidenceOutcome.COMPLIANT,
            regulation=REG_THREE_ZONES, detail="测量不完整，交由完整性校验", metric=()))
    if _dominant_zone(ctx) == "TIE":
        return GuardResult.ok(Evidence(
            rule_id="no_unique_dominant",
            outcome=EvidenceOutcome.VIOLATION,
            regulation=REG_THREE_ZONES,
            detail="地块与多个空间的重叠占比并列，或与所有空间均无重叠，无法判定主导功能，按 fail-closed 拒绝",
            metric=_ratio_metrics(ctx),
        ))
    return GuardResult.fail(Evidence(
        rule_id="no_unique_dominant", outcome=EvidenceOutcome.COMPLIANT,
        regulation=REG_THREE_ZONES, detail="存在唯一主导空间", metric=()))


_NO_UNIQUE_DOMINANT_GUARD = Guard(
    guard_id="no_unique_dominant",
    regulations=(REG_THREE_ZONES,),
    check=_check_no_unique_dominant,
    description_zh="主导功能唯一性校验：并列或全零 → fail-closed（不猜）",
)


def _make_dominant_guard(
    *,
    zone_name: str,
    regulation: Regulation,
    zone_label: str,
) -> Guard[ZoneJudgementContext]:
    """生成"主导功能为某空间"的确认 guard（几何事实，非优先级）。"""
    guard_id = f"dominant_{zone_name}"

    def check(ctx: ZoneJudgementContext) -> GuardResult:
        if not _all_ratios_measured(ctx):
            return GuardResult.fail(Evidence(
                rule_id=guard_id, outcome=EvidenceOutcome.COMPLIANT,
                regulation=regulation, detail="测量不完整，交由完整性校验", metric=()))
        dominant = _dominant_zone(ctx)
        if dominant == zone_name:
            # 确认"主导功能为 X"事实 → 触发对应转换
            return GuardResult.ok(Evidence(
                rule_id=guard_id, outcome=EvidenceOutcome.COMPLIANT,
                regulation=regulation,
                detail=f"地块主导功能为{zone_label}（重叠面积占比唯一最大）",
                metric=_ratio_metrics(ctx),
            ))
        return GuardResult.fail(Evidence(
            rule_id=guard_id, outcome=EvidenceOutcome.COMPLIANT,
            regulation=regulation, detail=f"地块主导功能不是{zone_label}", metric=()))

    return Guard(guard_id=guard_id, regulations=(regulation,),
                 check=check, description_zh=f"地块主导功能为{zone_label}")


_DOMINANT_ECOLOGICAL_GUARD = _make_dominant_guard(
    zone_name="ecological", regulation=REG_ECOLOGICAL_ZONE, zone_label="生态空间")
_DOMINANT_AGRICULTURAL_GUARD = _make_dominant_guard(
    zone_name="agricultural", regulation=REG_AGRICULTURAL_ZONE, zone_label="农业空间")
_DOMINANT_URBAN_GUARD = _make_dominant_guard(
    zone_name="urban", regulation=REG_URBAN_ZONE, zone_label="城镇空间")


class ThreeZonesOrchestrator(StateMachine[ThreeZonesState, ZoneJudgementContext]):
    """三区组合编排器：地块 → 三个子机测量 → 主导功能分类。

    无优先级编码：三个分类 guard 是几何占比的互斥事实分支，声明顺序
    与结果无关；并列或全零时 fail-closed（不猜），而非偏向任何空间。
    """
    machine_id = "three_zones"
    state_enum = ThreeZonesState
    initial_state = ThreeZonesState.PENDING

    def run(self, ctx: ZoneJudgementContext) -> MachineRun[ThreeZonesState]:
        """运行编排器，FAIL_CLOSED 终态归一为 completed=False（不猜即拒），
        并把结论自动写入 ctx（供组合机 land_use_validator 读取）。"""
        run = super().run(ctx)
        if run.final_state is ThreeZonesState.FAIL_CLOSED and run.completed:
            run = MachineRun(
                machine_id=self.machine_id, completed=False,
                final_state=run.final_state, steps=run.steps,
            )
        ctx.record_three_zones_verdict(run)
        return run

    transitions: tuple[Transition[ThreeZonesState, ZoneJudgementContext], ...] = (
        Transition(
            name="measure_all_zones",
            from_state=ThreeZonesState.PENDING,
            to_state=ThreeZonesState.ZONES_MEASURED,
            action=_run_all_zone_machines,
            description_zh="运行三个三区子机（测量重叠面积占比）",
        ),
        Transition(
            name="zone_measurement_failed",
            from_state=ThreeZonesState.ZONES_MEASURED,
            to_state=ThreeZonesState.FAIL_CLOSED,
            guards=(_MEASUREMENT_FAILED_GUARD,),
            description_zh="测量不完整 → fail-closed（不确定即拒）",
        ),
        Transition(
            name="no_unique_dominant_zone",
            from_state=ThreeZonesState.ZONES_MEASURED,
            to_state=ThreeZonesState.FAIL_CLOSED,
            guards=(_NO_UNIQUE_DOMINANT_GUARD,),
            description_zh="占比并列或全零 → fail-closed（不猜）",
        ),
        Transition(
            name="dominant_ecological",
            from_state=ThreeZonesState.ZONES_MEASURED,
            to_state=ThreeZonesState.ECOLOGICAL,
            guards=(_DOMINANT_ECOLOGICAL_GUARD,),
            description_zh="主导功能为生态空间",
        ),
        Transition(
            name="dominant_agricultural",
            from_state=ThreeZonesState.ZONES_MEASURED,
            to_state=ThreeZonesState.AGRICULTURAL,
            guards=(_DOMINANT_AGRICULTURAL_GUARD,),
            description_zh="主导功能为农业空间",
        ),
        Transition(
            name="dominant_urban",
            from_state=ThreeZonesState.ZONES_MEASURED,
            to_state=ThreeZonesState.URBAN,
            guards=(_DOMINANT_URBAN_GUARD,),
            description_zh="主导功能为城镇空间",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 模块级入口（便捷用法）
# ═══════════════════════════════════════════════════════════════════

_ECOLOGICAL_ZONE_MACHINE = EcologicalZoneMachine()
_AGRICULTURAL_ZONE_MACHINE = AgriculturalZoneMachine()
_URBAN_ZONE_MACHINE = UrbanZoneMachine()

THREE_ZONES_ORCHESTRATOR = ThreeZonesOrchestrator()


def judge_three_zones(
    parcel: Parcel,
    regions: ThreeZonesRegions,
    boundaries: ThreeLinesBoundaries | None = None,
) -> MachineRun[ThreeZonesState]:
    """一条调用完成三区判定：地块 + 三区边界 → 主导功能分类结论。

    boundaries 仅用于构造共享工作簿（三区判定本身不需要三线数据）；
    传 None 时按"无三线数据"处理。
    返回 MachineRun[ThreeZonesState]；completed=False 一律视为未决（拒绝）。
    """
    ctx = ZoneJudgementContext(
        parcel=parcel,
        boundaries=boundaries if boundaries is not None else ThreeLinesBoundaries(),
        zones=regions,
    )
    return THREE_ZONES_ORCHESTRATOR.run(ctx)
