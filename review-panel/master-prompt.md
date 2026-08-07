# Goal-Driven + Professional FSM + Constraint Engine + Reflection Panel

本 prompt 融合四种架构：

- **Professional FSM** (城市设计管理办法): 专业城市设计阶段状态机——P0→P1→P2→P3→P4→P5→P6。LLM 仅限于每个 Phase 的 `llm_slot` 中调用，流程控制全部由 CODE 决定。
- **Constraint Engine** (Layer 0-1): 61 条 CODE 约束，零 LLM，确定性执行。每个 Phase 的 prerequisites/exit_checks 由 CODE 执行。
- **Goal-Driven** (lidangzzz): Master → Subagent 持续迭代，直到 criteria 满足。while(criteria not met) { work() }
- **Reflection Panel** (hardlaw): 7 位 LLM 法官并行审查，只评判硬约束覆盖不到的维度。在全部 CODE 通过后才运行。

**核心原则：LLM 不遵守 prompt 中的长规则。专业工作流由状态机编码。LLM 只在规定槽位内做局部生成。**

---

## 专业工作流（Professional FSM）

城市设计的专业流程由 `constraints/procedure.py` 的 `UrbanDesignProcedure` 编码为确定性的状态机。
每个 Phase 都有：CODE prerequisites → LLM generation slot → CODE exit checks。

```
P0: 现状诊断与约束建立 (CODE_ONLY)
  → 读取 repo 全部物理数据，建立不可变场地事实基线
  → 零 LLM 参与

P1: 总体概念与品牌定位 (LLM_GENERATION, depends: P0)
  → 命名体系 + 定位展开 + 功能框架 + 协同逻辑
  → 城市设计管理办法第8条：确定城市风貌特色

P2: 空间结构与用地布局 (LLM_GENERATION, depends: P0+P1)
  → land_use.geojson + 空间结构 + 案例研究
  → 城市设计管理办法第8条：优化城市形态格局
  → 控制性详细规划编制办法：用地布局是控规核心

P3: 系统支撑与场景设计 (LLM_GENERATION, depends: P2)
  → 交通/蓝绿/公共空间 + 场景卡 + 用户画像
  → 城市设计管理办法第10条：协调市政工程

P4: 重点区域详细设计与文化叙事 (LLM_GENERATION, depends: P2+P3)
  → 三重点区详细方案 + 地标 + 文化叙事 + 荣誉体系
  → 城市设计管理办法第10条：建筑控制要求

P5: 实施分期与长期运营 (LLM_GENERATION, depends: P2+P3+P4)
  → 分期 + 活动 + 运营机制 + 国际传播 + 指标复算
  → 城市设计管理办法第14条：纳入控规

P6: 成果整合与合规终审 (CODE_ONLY, depends: P0-P5)
  → 整合 + 自检 + 全局约束引擎 + Reflection Panel
  → 城市设计管理办法第13条：征求专家和公众意见
```

### Phase 内部循环

```
for attempt in 1..max_retries:
    prerequisites (CODE) ──→ FAIL → rollback_to_dependency
    │
    ▼
    LLM generation slot ──→ 产出限定在 must_produce / must_not_produce
    │
    ▼
    exit_checks (CODE) ──→ PASS → next phase
    │                     │
    │                     └─→ FAIL (same fingerprint twice) → STALL → human_escalation
    │                     └─→ FAIL (new fingerprint) → retry with precise error context
    │
    └─→ attempt > max_retries → STALL → human_escalation
```

---

## Goal-Driven 主循环

```
orchestrator = Orchestrator(submission_path)
orchestrator.run()

while orchestrator.status != COMPLETED:
    if orchestrator.status == WAITING_FOR_LLM:
        request = orchestrator.current_llm_request
        # request.prompt 包含精确的任务说明 + 上一轮失败上下文
        # request.must_produce / request.must_not_produce 限定产出范围
        # 发送给 Generator Subagent 进行局部生成
        result = generator_agent.generate(request.prompt, request.output_files)
        orchestrator.continue_with_llm_result(result)

    elif orchestrator.status == ESCALATED:
        # 同一约束连续2轮 FAIL 或 超过max_retries
        # → 暂停，等待人工决策
        break
```

---

## 三层验证（不变）

```
while True:
    # ── GENERATION: Professional FSM drives phase-by-phase ──
    # 每个 Phase: CODE prereq → LLM slot → CODE exit
    # 详见 orchestrator.py

    # ── CONSTRAINT ENGINE (CODE, 0 LLM) ──
    $ python3 constraints/orchestrator.py --submission <path>
    # 所有 Phase 通过后自动运行 constraint_engine.validate()

    if critical_failures > 0:
        → precise_repair(failed) → retry

    if not all_pass:
        → precise_repair(failed) → retry

    # ── REFLECTION PANEL (LLM, 7 judges) ──
    7 judges parallel review → aggregate → route

    if ≥5/7 Not Refuted + 0 blocking:
        → completed
    elif ≥5/7 Not Refuted + non-blocking:
        → minor_fixes
    elif <5/7 Not Refuted + no blocking:
        → major_fixes (back to Generation)
    else:
        → human_escalation
```

---

## Generator Subagent Prompt（每 Phase 调用）

Generator Subagent 在每个 Phase 的 `llm_slot` 中被调用。它接收精确限定范围的 prompt。

```
你是百年京张AI创新带城市设计方案的生成者。

═══════════════════════════════════════════
当前阶段: {phase_name} ({phase_id})
═══════════════════════════════════════════

专业依据: {professional_reference}

## 任务
{llm_slot.task}

## 范围限定
{llm_slot.scope}

## 必须产出
{must_produce 列表}

## 禁止产出
{must_not_produce 列表}

## 硬性空间规则（代码会验证，确保满足）
{hard_spatial_rules 列表}

## 输入上下文
{from_p0/from_p1/... 数据}

## 输出文件
{output_files 列表}

## ⚠️ 重要提醒
1. 你只负责这个阶段的生成任务。不要判断自己是否完成——代码会验证。
2. 不要生产下一阶段的内容——流程由状态机控制。
3. 所有空间数据必须从给定的 GeoJSON 文件读取，不编造数字。
4. 如果这是修复轮次，下面会列出上一轮失败的具体检查——只修复这些问题，
   不要重新生成已通过检查的内容。
```

---

## Constraint Engine 快速命令

```bash
# 运行完整 FSM + Constraint Engine
python3 constraints/orchestrator.py --submission submissions/<login>/<slug>

# 只运行 FSM（到第一个 LLM slot 停止）
python3 run_pipeline.py --submission submissions/<login>/<slug>

# JSON 输出
python3 constraints/orchestrator.py --submission submissions/<login>/<slug> --json

# 单独运行约束引擎
python3 constraints/engine.py submissions/<login>/<slug> --json

# 更新约束注册表
python3 constraints/extractors.py
```

---

## Master Loop 启动模板

将以下内容发给 Claude Code：

```
# Goal-Driven + Professional FSM: haidian 城市设计

Goal: 在 submissions/<github-login>/<proposal-slug>/ 下生成完整 formal 方案包

Criteria:
  Gate 1: 全部 6 个专业 Phase 的 CODE exit_checks PASS
  Gate 2: constraint_engine all_pass (61 条硬约束)
  Gate 3: 7 法官 ≥5/7 Not Refuted + 0 blocking

工作目录: /Users/ljj/Projects/haidian

请运行:
  python3 constraints/orchestrator.py --submission submissions/<login>/<slug>

Orchestrator 会在每个 Phase 的 llm_slot 停止，输出精确限定的生成 prompt。
请将每个 prompt 发送给 Generator Subagent，生成结果写入对应文件后，
运行 --continue 继续到下一个 Phase。
```

---

## Stall Detection

Orchestrator 自动检测：
- 同一 Phase 的同一 exit_check 连续 2 轮 FAIL（指纹相同）→ STALL
- 超过 Phase max_retries（默认3）→ STALL
- 总迭代超过 max_iterations（默认50）→ STALL

STALL 状态 → 暂停自动循环 → 输出精确失败信息 → 等待人工决策。

## 关键文件引用

| 文件 | 用途 |
|------|------|
| `constraints/procedure.py` | 专业城市设计状态机（6 Phase, CODE steps + JUDGMENT points） |
| `constraints/orchestrator.py` | Goal-Driven + FSM 编排器（驱动整个自主循环） |
| `run_pipeline.py` | 单一入口点（替代碎片化命令） |
| `constraints/engine.py` | Layer 1: 约束引擎（33+ CODE 检查函数） |
| `constraints/extractors.py` | 从 repo 物理文件自动提取约束 |
| `constraints/registry.json` | 43 条约束注册表 |
| `review-panel/statutes.json` | 7 部 LLM 法官评审法规 |
| `review-panel/procedure.json` | 审查流程状态机 |
| `review-panel/judge-prompts/01-07-*.md` | 7 位法官详细审查指令 |
