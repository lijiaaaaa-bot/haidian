"""state_machine.py — deterministic state machine base classes.

The "Three Zones Three Lines" (三区三线) judgment machines are built on this
foundation. This module defines the MECHANISM only:

    State / Transition / Guard / Action / Evidence

It contains no domain knowledge — no redlines, no farmland, no parcels.
Those live in three_lines.py / three_zones.py / land_use_validator.py.

──────────────────────────────────────────────────────────────────────
Determinism contract (HARD):
  - Zero LLM involvement: every decision is a pure function of the input.
  - No randomness, no wall-clock dependence, no I/O inside guards/actions.
  - Same input + same transition table => same result, bit for bit.

Fail-closed contract (HARD):
  - Any uncertainty rejects. The fail-closed triggers are:
      1) a Guard raises an exception
      2) no Transition is applicable at the current state
      3) an Action raises an exception
      4) the machine detects a state loop (no progress)
  - In every case the machine returns MachineRun(completed=False) with a
    VIOLATION evidence citing SYSTEM_FAIL_CLOSED.

Evidence contract (HARD):
  - Every Guard MUST bind at least one Regulation (a clause citation such
    as "自然资发〔2022〕142号"). A guard without regulations fails closed.
  - No text generation: evidence fields are structured values plus fixed
    Chinese wording from regulation constants — never model-produced prose.

Composition:
  - Each sub-machine runs independently via run(ctx).
  - To compose, an orchestrator machine stores sub-machine results in
    ctx.results (store/load) and its own guards read them. Sub-machines
    stay pure; composition happens through the shared context.

Style: mirrors haidian/constraints/domain.py — frozen dataclasses, Enums,
typed fields, Chinese labels, "Source:" provenance comments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

StateT = TypeVar("StateT", bound=Enum)
CtxT = TypeVar("CtxT", bound="MachineContext")


# ═══════════════════════════════════════════════════════════════════
# Evidence model — every judgment must cite its legal basis
# ═══════════════════════════════════════════════════════════════════

class EvidenceOutcome(Enum):
    """What a piece of evidence proves about the parcel."""
    COMPLIANT = "compliant"    # 判定通过的依据（满足条款）
    VIOLATION = "violation"    # 判定失败的原因（违反条款）


@dataclass(frozen=True)
class Regulation:
    """One citable clause. Every Guard binds at least one.

    Source: notes/01-territorial-spatial-planning.md §三线详细定义
    """
    doc_short: str        # 简称，如 "自然资发〔2022〕142号"
    doc_title_zh: str     # 文件全称
    article_zh: str = ""  # 条款位置，如 "第3条" / "第三十三条" / "管控要求"
    rule_zh: str = ""     # 该条款的管控要求（固定中文文案，非生成文本）


@dataclass(frozen=True)
class Evidence:
    """One judgment trace: which rule, based on which clause, with what numbers.

    detail must be a fixed wording string chosen by code, never generated text.
    metric carries the deterministic quantitative basis (e.g. overlap area).
    """
    rule_id: str
    outcome: EvidenceOutcome
    regulation: Regulation
    detail: str
    metric: tuple[tuple[str, float], ...] = field(default_factory=tuple)


SYSTEM_FAIL_CLOSED = Regulation(
    doc_short="SYSTEM-PRINCIPLE",
    doc_title_zh="系统设计原则：fail-closed（未决即拒）",
    article_zh="",
    rule_zh=(
        "当输入不完整、无可适用规则、或执行异常时，默认拒绝，"
        "而非默认放行。所有建设用地判定均以'不允许'为缺省值。"
    ),
)


def _fail_closed_evidence(rule_id: str, detail: str) -> Evidence:
    """Build the canonical fail-closed evidence (deterministic, fixed wording)."""
    return Evidence(
        rule_id=rule_id,
        outcome=EvidenceOutcome.VIOLATION,
        regulation=SYSTEM_FAIL_CLOSED,
        detail=detail,
    )


# ═══════════════════════════════════════════════════════════════════
# Guard / Transition / Action
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GuardResult:
    """Verdict of one Guard evaluation.

    passed=True  → evidences 是该判定"满足条款"的依据。
    passed=False → evidences 是违规详情（同样逐条引用条款）。
    """
    passed: bool
    evidences: tuple[Evidence, ...] = ()

    @staticmethod
    def ok(*evidences: Evidence) -> "GuardResult":
        return GuardResult(passed=True, evidences=tuple(evidences))

    @staticmethod
    def fail(*evidences: Evidence) -> "GuardResult":
        return GuardResult(passed=False, evidences=tuple(evidences))


@dataclass(frozen=True)
class Guard(Generic[CtxT]):
    """A named, citable predicate over the context.

    HARD: regulations must be non-empty — evidence is mandatory, not optional.
    HARD: check must be a pure function (no IO, no randomness, no LLM).
    """
    guard_id: str
    regulations: tuple[Regulation, ...]
    check: Callable[[CtxT], GuardResult]
    description_zh: str = ""

    def evaluate(self, ctx: CtxT) -> GuardResult:
        """Run the guard. Fail-closed on missing citations or exceptions."""
        if not self.regulations:
            # 强制 evidence：无条款引用的判定一律拒绝
            return GuardResult.fail(_fail_closed_evidence(
                self.guard_id,
                f"guard '{self.guard_id}' 未绑定任何法条引用（强制 evidence 要求），按 fail-closed 拒绝",
            ))
        try:
            return self.check(ctx)
        except Exception as exc:  # noqa: BLE001 — fail-closed is the contract
            # 防御性兜底：guard 异常视为"不确定"，按 fail-closed 拒绝
            return GuardResult.fail(_fail_closed_evidence(
                self.guard_id,
                f"guard '{self.guard_id}' 执行异常（{exc.__class__.__name__}），按 fail-closed 拒绝",
            ))


@dataclass(frozen=True)
class Transition(Generic[StateT, CtxT]):
    """One rule in the transition table: from_state → to_state.

    A transition fires when ALL its guards pass. It is not an if-else
    branch — it is a declarative row that tests can enumerate.
    """
    name: str
    from_state: StateT
    to_state: StateT
    guards: tuple[Guard[CtxT], ...] = ()
    action: Callable[[CtxT], None] | None = None  # 记账副作用（如写入中间结论），须为纯函数
    description_zh: str = ""


# ═══════════════════════════════════════════════════════════════════
# Step / Run results — the deterministic output of execution
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class StepResult(Generic[StateT]):
    """Result of ONE step() call."""
    transition_name: str
    new_state: StateT
    passed: bool
    evidences: tuple[Evidence, ...] = field(default_factory=tuple)

    @property
    def violations(self) -> tuple[Evidence, ...]:
        return tuple(e for e in self.evidences if e.outcome is EvidenceOutcome.VIOLATION)


@dataclass(frozen=True)
class MachineRun(Generic[StateT]):
    """Result of a full run(ctx): the machine's complete verdict trace.

    completed=True  → 正常走到终态（终态可能是 ALLOWED，也可能是某个
                      合法的 REJECTED 终态 —— 机器判定正确即为完成）。
    completed=False → fail-closed：未决、异常或停滞，一律视为拒绝。
    """
    machine_id: str
    completed: bool
    final_state: StateT
    steps: tuple[StepResult[StateT], ...] = field(default_factory=tuple)

    @property
    def evidences(self) -> tuple[Evidence, ...]:
        return tuple(e for s in self.steps for e in s.evidences)

    @property
    def violations(self) -> tuple[Evidence, ...]:
        return tuple(e for s in self.steps for e in s.violations)

    @property
    def last_transition(self) -> str:
        return self.steps[-1].transition_name if self.steps else "(none)"


# ═══════════════════════════════════════════════════════════════════
# Context — the shared judgment workbook
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MachineContext:
    """Base judgment context.

    Sub-machines store their intermediate verdicts into results via store();
    orchestrator machines read them via load(). This is the composition
    mechanism: sub-machines stay independent AND composable.
    Concrete fields (parcel geometry, three-line boundaries) are defined
    by the submodules (three_lines.py etc.).
    """
    results: dict[str, Any] = field(default_factory=dict)

    def store(self, key: str, value: Any) -> None:
        self.results[key] = value

    def load(self, key: str, default: Any = None) -> Any:
        return self.results.get(key, default)


# ═══════════════════════════════════════════════════════════════════
# The StateMachine base class
# ═══════════════════════════════════════════════════════════════════

class StateMachine(Generic[StateT, CtxT]):
    """Deterministic state machine base class.

    Subclasses declare, as class attributes:
        machine_id:        str  (机器标识，如 "three_lines")
        state_enum:        type[StateT]   (状态枚举)
        initial_state:     StateT         (初始状态)
        transitions:       tuple[Transition[StateT, CtxT], ...]
        fail_closed_state: StateT | None  (可选：fail-closed 时显式转入的拒绝态)

    Execution model:
      - step(ctx, state): scan the transition table in declaration order;
        the first transition whose ALL guards pass fires.
      - run(ctx): advance from initial_state until a terminal state
        (no outgoing transitions) or fail-closed.
      - State loops are impossible by construction in a linear judgment
        chain; if one is configured, run() fails closed instead of hanging.
    """

    machine_id: str = "state_machine"
    state_enum: type[StateT]  # subclass responsibility
    initial_state: StateT     # subclass responsibility
    transitions: tuple[Transition[StateT, CtxT], ...] = ()
    fail_closed_state: StateT | None = None

    # ── configuration self-check (call in tests / __init__) ──
    def validate(self) -> list[str]:
        """Return config problems; empty list means the table is legal."""
        problems: list[str] = []
        try:
            valid_states = set(self.state_enum)
        except AttributeError:
            problems.append(f"{self.machine_id}: 缺少 state_enum 类属性")
            return problems
        if self.initial_state not in valid_states:
            problems.append(f"{self.machine_id}: initial_state {self.initial_state!r} 不在状态枚举中")
        if self.fail_closed_state is not None and self.fail_closed_state not in valid_states:
            problems.append(f"{self.machine_id}: fail_closed_state {self.fail_closed_state!r} 不在状态枚举中")
        for t in self.transitions:
            if t.from_state not in valid_states:
                problems.append(f"{self.machine_id}: 转换 '{t.name}' from_state 非法: {t.from_state!r}")
            if t.to_state not in valid_states:
                problems.append(f"{self.machine_id}: 转换 '{t.name}' to_state 非法: {t.to_state!r}")
        return problems

    # ── single step ──
    def step(self, ctx: CtxT, current: StateT) -> StepResult[StateT]:
        """Advance one transition, or fail closed if none applies."""
        for t in self.transitions:
            if t.from_state is not current:
                continue
            guard_results = [g.evaluate(ctx) for g in t.guards]
            if all(r.passed for r in guard_results):
                evidences = tuple(e for r in guard_results for e in r.evidences)
                if t.action is not None:
                    try:
                        t.action(ctx)
                    except Exception as exc:  # noqa: BLE001 — fail-closed contract
                        return StepResult(
                            transition_name=t.name,
                            new_state=current,
                            passed=False,
                            evidences=evidences + (_fail_closed_evidence(
                                t.name,
                                f"action '{t.name}' 执行异常（{exc.__class__.__name__}），按 fail-closed 拒绝",
                            ),),
                        )
                return StepResult(transition_name=t.name, new_state=t.to_state, passed=True, evidences=evidences)
        # 无可适用转换 → 未决，按 fail-closed 拒绝
        return StepResult(
            transition_name="(fail-closed)",
            new_state=current,
            passed=False,
            evidences=(_fail_closed_evidence(
                "no_applicable_transition",
                f"状态 {current!r} 下没有任何转换规则通过 guard，按 fail-closed 拒绝",
            ),),
        )

    # ── full run ──
    def run(self, ctx: CtxT) -> MachineRun[StateT]:
        """Run from initial_state to a terminal state or fail-closed."""
        state = self.initial_state
        steps: list[StepResult[StateT]] = []
        visited: set[StateT] = set()

        while True:
            if state in visited:
                # 状态循环 → 停滞，fail-closed（防止配置错误导致死循环）
                steps.append(StepResult(
                    transition_name="(state-loop)",
                    new_state=state,
                    passed=False,
                    evidences=(_fail_closed_evidence(
                        "state_loop",
                        f"检测到状态循环（{state!r} 重复访问），按 fail-closed 拒绝",
                    ),),
                ))
                return MachineRun(
                    machine_id=self.machine_id, completed=False,
                    final_state=state, steps=tuple(steps),
                )
            visited.add(state)

            result = self.step(ctx, state)
            steps.append(result)
            if not result.passed:
                final = self.fail_closed_state if self.fail_closed_state is not None else state
                return MachineRun(
                    machine_id=self.machine_id, completed=False,
                    final_state=final, steps=tuple(steps),
                )

            state = result.new_state
            if not self._has_outgoing(state):
                return MachineRun(
                    machine_id=self.machine_id, completed=True,
                    final_state=state, steps=tuple(steps),
                )

    def _has_outgoing(self, state: StateT) -> bool:
        return any(t.from_state is state for t in self.transitions)
