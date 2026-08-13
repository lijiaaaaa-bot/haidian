# Goal-Driven 入口程序设计（lidangzzz 模式）

**日期**：2026-08-07
**状态**：已实现（2026-08-13 归档）——见下方「实现与分歧说明」。
**范围**：为百年京张AI创新带城市设计项目设计新的自主生成入口程序。取代 Phase/FSM 编排思路（`constraints/orchestrator.py`、`run_pipeline.py` 不在本设计内，保持原样不动）。

---

## 实现与分歧说明（2026-08-13 归档备注）

本设计已经落地为 haidian 的重型自主路径，但**实际实现与设计稿有以下分歧**，读代码时以实际代码为准：

| 设计稿 | 实际实现 |
|---|---|
| `scripts/llm_client.py`（§5.1） | **未按此拆分**。实际 LLM 客户端是 `scripts/mlx_client.py`（`mlx_chat`），且支持本地 MLX 与 DeepSeek 双后端 |
| `scripts/submission_tools.py`（§5.1 四工具） | **未单独成文件**。工具逻辑内联在 `scripts/goal_driven_loop.py` 内 |
| `scripts/panel_runner.py`（§5.1） | 未落地；Reflection Panel 仍走 `review-panel/` 的独立评审流程 |
| `scripts/goal_driven_loop.py`（设计估 ~300 行） | **已实现，但膨胀到 ~2600 行**，内含 Master 循环、后端路由、状态管理、`--resume`/CLI |
| `docs/goal-driven-entry.md` | 本文件 |

**权威入口**：`bash scripts/run_autonomous.sh` → `python3 scripts/goal_driven_loop.py --submission submissions/test/test`。

**规范裁决（2026-08-13）**：
- `scripts/goal_driven_loop.py` 是 haidian 的**唯一重型自主实现**（canonical），重型任务一律走它；
- `~/Projects/goal-driven` 框架包是**通用库**，与 haidian 无代码交叉，不迁移、不删除 `goal_driven_loop.py`（108KB 迁移高风险低收益），也不删除 `scripts/goal_fix_tests.py`；
- `/goal-driven` 命令保持轻量协议，仅做「验证器→修一处→再验证」的手动循环。


---

## 0. 设计原则

本设计只承认一个循环：

```
while (criteria not met) {
    let the subagent work on solving the problem
}
```

由此派生的四条纪律：

1. **Master 只做三件事**：跑确定性验证、把「具体失败 + 证据」喂给 subagent、决定继续/升级。Master 绝不告诉 subagent「你现在处于第 N 阶段，应该生成用地布局」。
2. **反馈即 prompt**：subagent 每次收到的任务是"修复以下验证失败"，修法由 subagent 自己决定。
3. **不区分「生成」与「修复」**：scaffold 生成的占位包本身就是第一轮验证失败（SCAFFOLD-DRAFT 标记、占位图纸、bbox 分区用地）——第一次 subagent 调用就是一次普通的修复轮。不需要 Phase 概念。
4. **LLM 在程序之内**：subagent 是程序调用的对象（tool-use 循环），不是程序之外的代码生成器。

---

## 1. 现状分析（接口梳理）

### 1.1 Gate 1 现有设施：`constraints/engine.py`

**调用方式**：

```python
engine = ConstraintEngine(repo_root="/path/to/haidian")
engine.load_registry()                      # 读 constraints/registry.json
results = engine.validate("submissions/<login>/<slug>")   # → list[ConstraintResult]
report  = engine.report(results)            # → dict（可 JSON 序列化）
```

**返回结构**：`ConstraintResult` 字段 = `constraint_id / name / outcome(PASS|FAIL|SKIP|ERROR) / severity(critical|high|medium) / category(spatial|compliance|metric|attributes|package) / detail / evidence / check_type("CODE") / elapsed_ms`。

**失败信息长这样**（`detail` + `evidence` 已足够喂给 subagent）：

```
C-LANDUSE-COVERAGE  FAIL  severity=critical  category=spatial
  detail:   land_use 未完全覆盖 site_boundary: 间隙面积约 8423 m² (1.3%)
  evidence: geometry/land_use.geojson: gap area 8423 m²
```

**关键辅助**：
- `report["all_code_checks_pass"]`、`report["ready_for_llm_review"]`（critical=0）——Gate 1 判定直接复用。
- `ConstraintResult.fingerprint`（`sha256(constraint_id + detail)` 前 16 位）——stall 检测的稳定指纹，已内置。
- `engine.stall_check(current, previous)`——两组结果指纹集合相等的判断，可复用。

**实际规模**（以 `registry.json` 为准；文档各处 43/53/61 说法不一）：

| 项 | 值 |
|---|---|
| 注册表总约束 | 43 |
| enabled CODE 约束（引擎实际执行） | 33（spatial 19 / compliance 11 / metric 3）|
| 严重级 | critical 19 / high 14 |
| 内置 check 函数 | 16 个（verify_crs_used / verify_area_tolerance / verify_land_use_coverage / verify_enum_values / grep_forbidden_patterns …）|

注册表是数据驱动（`extractors.py` 自动生成 + `manual_overrides`），新增约束只需加 JSON 条目 + check 函数——这是后续扩展三区三线状态机的天然扩展点（见 §5.4）。

### 1.2 Gate 2 现有设施：Reflection Panel

**`review-panel/statutes.json`**：7 部法规，每部含 `physical_evidence[]`、`violations[]`（name/severity/detection）、`pass_condition`、`default_to_reject`。

| # | statute | 中文名 | default_to_reject | blocking |
|---|---|---|---|---|
| 1 | package_integrity | 格式完整性 | true | – |
| 2 | spatial_quality | 空间数据质量 | true | – |
| 3 | proposal_depth | 方案文本深度 | true | – |
| 4 | task_coverage | 任务覆盖完整性 | true | – |
| 5 | figure_quality | 图纸质量 | **false**（不确定给通过）| – |
| 6 | metric_verifiability | 指标可复算性 | true | – |
| 7 | compliance_and_boundaries | 合规与边界条款 | true | **true** |

**`review-panel/judge-prompts/01-07-*.md`**：7 个 prompt 模板，结构完全一致：
1. 角色定位（「你只检查 X，不评价方案好不好」）
2. **CODE PRECHECK** 块——「以下约束已由引擎验证 PASS，不要重复检查」
3. STATUTE JSON 摘录
4. 需要执行的物理检查（引用 `<submission_path>` 下的具体文件）
5. 禁止事项
6. **OUTPUT CONTRACT**——JSON verdict：`{finding, refuted, confidence, blocking, evidence_refs[], reasoning, findings[]}`，终端最后一行必须是 `Refuted` / `Not Refuted`

**`review-panel/procedure.json`**：审查流程与路由规则：

```
panel_review → approved    : ≥5/7 Not Refuted + 0 blocking
panel_review → minor_fixes : ≥5/7 Not Refuted 但有非 blocking Refuted
panel_review → major_fixes : <5/7 Not Refuted 且无 blocking
panel_review → blocking    : 任何 blocking=true 的 Refuted
```
另有 `max_rounds: 10`、`stall_threshold: 2`——新入口直接复用这两个数字。

**注意**：judge prompt 里写着「读取 `<submission_path>/xxx.json`」——LLM 法官无文件系统，证据必须由 Master 注入（见 §4.1）。CODE PRECHECK 模式也提示了一条通用做法：**凡确定性引擎能算的，先算好告诉法官，不要让它自己算**（LLM 不会可靠地算 SHA-256 或投影面积）。

### 1.3 脚手架与收尾设施

**`scripts/scaffold_ai_submission.py`**：

```
python3 scripts/scaffold_ai_submission.py <submission_dir> \
    --stage formal --agent-id <id> --agent-name <name> --proposal-title <title>
```

产出完整占位包：`proposal.md`（含 `SCAFFOLD-DRAFT` 标记）、`geometry/`（site_boundary/key_areas 取自 brief 官方或 provisional 几何；land_use 为 bbox 分区；buildings/roads/green/public/phasing 为占位）、`metrics.json`、`compliance_matrix.json`、`standard_matrix.json`、`design_depth_matrix.json`、`self_check.json`、`report/`（proposal.html + narrative + copyright）、`drawings/`（MINIMAL_PDF 占位）、`visual/index.html`、`manifest.json`（`package_state="scaffold"` + 全部文件 SHA-256 + `known_blockers`）。

**`scripts/finalize_submission.py`**：scaffold → `ready_for_review` 的收尾门禁。`package_state` 必须是 `scaffold`，否则报错。它本身就是「占位检测器」：

```
errors:
- proposal.md still contains the SCAFFOLD-DRAFT marker
- <proposal.md|report/proposal.html|visual/index.html> is unchanged from the generated scaffold
- all five proposal figures must be regenerated: ...
- at least one participant-controlled design geometry layer must change
- <drawings/*.pdf> is unchanged from the placeholder drawing / has no pages
```

⚠️ **改造点**：finalize 要求 `package_state == "scaffold"`，而 Goal-Driven 循环每一轮 subagent 修改后都要重新收尾。需要把 finalize 的核心逻辑提取为库函数 `finalize_package(submission_dir, require_scaffold=False)`（见 §5.2）。

**`scripts/self_check_submission.py`**：参赛者侧预提交门禁，串行跑 4 个子校验（`validate_local_submission.py` + `spatial_review.py` + `visual_review.py` + `professional_review.py`），输出 `ok / stage / can_enter_formal_review / next_actions`。**定位**：PR 提交前的人工/CI 门禁，不进 Master 循环（避免每轮 4 个子进程开销）；最终 DONE 前跑一次。

**`scripts/ai_review_submission.py`（先例参考）**：现有 LLM 评审客户端，值得沿用的模式：
- API 凭据从环境变量读（`OPENAI_API_KEY` / `OPENAI_BASE_URL`），模型可配置；
- 原子写入（`path.with_name(f".{name}.tmp-{pid}")` → `replace`）；
- 输出必须过 strict schema，且**确定性门禁永远覆盖模型声明**；
- 评审产物只写到 gitignore 的 `.maintainer-review/` 树内。

### 1.4 LLM 环境

- DeepSeek 通过 Anthropic-compatible API 可用：`ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`，模型 `deepseek-v4-pro`，用 `anthropic` Python SDK（`client.messages.create(...)`）直接调用。
- `anthropic` 包目前**不在** `requirements-review.txt`（现有：jsonschema / Pillow / pyproj / shapely）——需新增。
- DeepSeek 端点的能力边界（tool-use 支持、图像输入、prompt caching 是否生效）**未验证**，本设计为每个假设都留有降级路径（见 §3.1、§4.2、§5.4）。

---

## 2. 入口程序设计（Master Loop）

### 2.1 结构总览

```
                    ┌──────────────────────────────────────────┐
                    │  Master (while loop, ~60 行)              │
                    │  不微操 subagent，只验证 + 反馈 + 决策      │
                    └───────┬──────────────┬───────────────────┘
                            │              │
              Gate 1 (CODE) │              │ Gate 2 (LLM)
                            ▼              ▼
              ┌──────────────────┐  ┌────────────────────┐
              │ ConstraintEngine │  │ 7 judge 并行审查    │
              │ + finalize 收尾  │  │ (DeepSeek × 7)      │
              └────────┬─────────┘  └─────────┬──────────┘
                       │ 失败反馈              │ findings
                       ▼                      ▼
              ┌──────────────────────────────────────────┐
              │  DeepSeek Subagent（tool-use 循环）        │
              │  read_file / write_file / run_python      │
              │  自己决定怎么改提交包                       │
              └──────────────────────────────────────────┘
```

### 2.2 伪代码（Master 主循环，约 60 行）

```python
# ── 常量（复用 procedure.json 的数字）──────────────────────────────
MAX_ROUNDS      = 10          # procedure.json max_rounds
STALL_THRESHOLD = 2           # procedure.json stall_threshold

# ── 初始化 ────────────────────────────────────────────────────────
def main(login, slug, resume=False):
    submission = repo / "submissions" / login / slug
    state = load_state(submission) if resume else new_state()
    if not submission.exists():
        scaffold(submission, login, slug)          # 占位包, package_state=scaffold
    engine = ConstraintEngine(repo); engine.load_registry()

    while state.rounds <= MAX_ROUNDS:
        # ── Gate 1a: 确定性约束引擎 ───────────────────────────
        failures = [r for r in engine.validate(submission)
                    if r.outcome == FAIL]

        # ── Gate 1b: 收尾门禁（占位检测 + 哈希锁定）────────────
        if not failures:
            ferrors = finalize_package(submission) # require_scaffold=False
            failures += [as_failure(e) for e in ferrors]

        # ── 有失败 → 反馈给 subagent，继续循环 ─────────────────
        if failures:
            if is_stalled(state, failures):        # 指纹连续 2 轮相同
                escalate(state, failures); return  # 人工接管
            feedback = format_feedback(failures)   # 只含失败项+evidence
            deepseek_work(submission, feedback, state.history)
            state.record_round(failures)
            continue                               # 回到 Gate 1a，不进入 Gate 2

        # ── Gate 2: 7 法官并行审查 ────────────────────────────
        verdicts = run_panel(submission)           # 7 个并行 DeepSeek 调用
        verdict  = aggregate(verdicts)             # procedure.json 路由

        if verdict.kind == APPROVED:
            run_self_check(submission)             # PR 前门禁（可选）
            print("DONE"); return

        if verdict.kind == BLOCKED:                # blocking refuted
            escalate(state, verdict); return       # 人工接管，不自动改

        deepseek_work(submission, verdict.findings, state.history)
        state.record_round(verdict.fingerprints)
        # 继续 → 重新跑 Gate 1（finalize 哈希会变化，必须重新收尾）
```

### 2.3 三个 Gate 的精确定义

| Gate | 判定 | 通过条件 |
|---|---|---|
| Gate 1a | `engine.validate()` + `engine.report()` | `all_code_checks_pass == True`（33 条 CODE 约束零 FAIL）|
| Gate 1b | `finalize_package()` | 无错误（无 SCAFFOLD-DRAFT、必改文件已改、图纸非占位、PDF 非空、哈希锁定、`package_state=ready_for_review`）|
| Gate 2 | 7 judge 并行 | `≥5/7 Not Refuted + 0 blocking`（procedure.json 路由规则）|

### 2.4 收敛性设计（不引入状态机的收敛控制）

- **反馈颗粒度**：`format_feedback()` 只输出 FAIL 项，按 fingerprint 去重、按 severity 排序；每项 = `constraint_id + name + detail + evidence`（evidence 已含文件与位置）。这就是 subagent 的全部任务描述。
- **历史上下文**：`state.history` 保留最近 3 轮的反馈摘要（每轮一行：修了什么、哪些指纹仍失败），追加到 subagent prompt，避免重复修法。
- **Stall 检测**：`is_stalled()` 用 `ConstraintResult.fingerprint`（引擎已内置）。连续 `STALL_THRESHOLD`(2) 轮失败指纹集合**完全相同** → 第 3 轮 subagent 会收到历史并被告知「已修 2 轮未变，请换一种方法或明确报告不可行」；若第 3 轮指纹仍相同 → `escalate()`。总轮数超 `MAX_ROUNDS`(10) → 同样 escalate。
- **升级输出**：写 `.goal-driven/<slug>/escalation.md`（goal、轮次、持续失败的指纹+evidence、最近尝试摘要、建议人工动作），退出码非 0。人工处理后可 `--resume` 续跑（可选 `--human-note` 把人工指示并入下一轮 subagent prompt）。

### 2.5 状态与日志

- 运行状态放 `.goal-driven/<slug>/`（仿 `.maintainer-review/` 先例，gitignore），**不进提交包**：`loop-state.json`（rounds / 指纹历史 / 花费）、`run.log`、`cost.jsonl`（每轮 token 与费用）。
- 提交包内唯一写入方是 subagent（经工具）和 finalize；Master 从不直接改提交文件。

---

## 3. DeepSeek Subagent 设计

### 3.1 文件操作：tool-use（带降级路径）

**推荐：tool-use 模式**。Anthropic SDK 的 `tools=[...]` 循环对 DeepSeek 的 Anthropic 兼容端点大概率可用（本端点即按 messages API 实现），且这是「LLM 在程序之内」最自然的形态。Master 实现工具循环：`messages.create` → 若有 `tool_use` 块 → 执行 → 回填 `tool_result` → 再发，单次调用上限 20 个工具轮次。

工具集（**最小四件**，全部受限到白名单根目录）：

| 工具 | 输入 | 说明 |
|---|---|---|
| `read_file` | path | 白名单内任意文件全文（submission/、brief/site-package/、templates/、data/source_registry.json 只读）|
| `list_dir` | path | 目录树（含文件大小；GeoJSON 只列名不列坐标，避免刷 token）|
| `write_file` | path, content | 仅限 `submissions/<login>/<slug>/`；原子写入；`.json`/`.geojson` 先 `json.loads` 预校验，非法 JSON 直接拒绝并报错 |
| `run_python` | code | 沙箱：仅 shapely/pyproj/PIL/matplotlib 可用，cwd 锁在 repo 内、禁网络、10s 超时；用于几何复算、拓扑修复、图纸生成 |

**为什么必须有 `run_python`（这是唯一"非最简"但承重的部分）**：Gate 1 的硬失败主要落在空间拓扑上——「land_use 未完全覆盖，间隙 8423 m²」「面积偏差 3%」「polygon 重叠」。LLM 靠手写坐标**不可能**修好这些（要求亚 m² 级闭合）。没有计算路径，循环必然在空间约束上 stall。`run_python` 让 subagent 自己写修复逻辑（例如对现有 land_use 做 `unary_union` 差集重分、按比例重算分区、用 PIL/matplotlib 生成技术图解风图纸），既符合「subagent 决定怎么修」，又把几何正确性交给确定性代码而非模型猜数。`write_file` 的 JSON 预校验 + `run_python` 的沙箱是仅有的两道护栏。

**降级路径（Plan B）**：若 DeepSeek 端点不支持 tool-use，切换为同一 prompt 的**结构化输出契约**——subagent 只返回 `{"reads": [...], "writes": [{"path", "content"}], "scripts": [{"name", "code"}]}`，Master 代为执行。二者只是传输层不同，prompt 与工具语义完全一致，切换成本 = 一个配置开关。

### 3.2 Prompt 模板（Master → Subagent，每次调用）

```
你是百年京张AI创新带城市设计方案的生成者。你不是评审者，不要判断自己是否完成——代码会验证。

## Goal
在 submissions/<login>/<slug>/ 生成完整 formal 城市设计方案包，满足三个 Gate：
  Gate 1: 33 条确定性约束全部 PASS（面积容差±5%、图层拓扑覆盖、枚举值、禁语措辞…）
  Gate 1b: 包收尾通过（无 SCAFFOLD-DRAFT 占位、图纸非占位、哈希锁定、package_state=ready_for_review）
  Gate 2: 7 位评审法官 ≥5/7 Not Refuted 且 0 blocking

## 权威数据（需要时用 read_file 读取，不得编造数字）
- brief/site-package/design_brief.json       三层范围、关键区、坐标政策、任务清单
- brief/site-package/agent_taskbook.json     六大 agent 任务、boundary clause、强制措辞
- brief/site-package/allowed_design_space.json  允许图层、枚举、几何政策
- brief/site-package/geometry/provisional_boundaries.geojson  场地边界（official/provisional 标记）
- brief/site-package/schemas/*.json          各 JSON 的 schema
- data/source_registry.json                  来源可用等级（formal / background / provisional）
- templates/proposal.md                      12 章模板与引用格式要求
- data/processed/agent_fact_pack.md          整理过的任务清单与资料缺口

## 当前提交包（文件树 + 大小）
<list_dir 输出>

## 本轮任务：修复以下验证失败（只修这些，不要动已通过的内容）
<format_feedback 输出：每项 constraint_id / severity / detail / evidence>

## 历史（最近 3 轮，供你避免重复修法）
<state.history 摘要>

## 工具
你可以调用 read_file / list_dir / write_file / run_python。
- 所有 JSON/GeoJSON 写入必须符合 brief/site-package/schemas/ 的 schema。
- 空间几何用 run_python 从现有 GeoJSON 计算得到，禁止手写坐标。
- 图纸用 run_python + matplotlib/PIL 生成技术图解风格（参考 brief/site-package/visual_style_recommendations.json）；
  每张图必须含标题、图例、来源与 official/provisional 标注；provisional 边界用虚线/淡色。
- 不要修改 manifest.json 与 geometry/site_boundary.geojson 的来源标记——收尾由 Master 负责。

## 完成
完成你认为的修复后结束。Master 会重新验证；若某些失败你判断无法修复，明确说明原因与需要的资料。
```

关键点：**prompt 里不贴文件内容**——只给文件树 + 反馈 + 历史，具体内容由 subagent 用工具按需读取。这是 token 成本的第一道闸门，也让「读哪些数据」成为 subagent 自己的判断（符合 Goal-Driven 精神）。

### 3.3 内容契约（subagent 的边界）

- 只允许通过工具写 `submissions/<login>/<slug>/` 内的文件；
- 不得写 `manifest.json`（Master 收尾时统一刷新哈希）；
- 不得改 `geometry/site_boundary.geojson` 的 `geometry_role / official_boundary / source_type`（锁定属性，引擎 C-BOUNDARY 系列约束守护）；
- 每次调用结束后 Master 无条件重跑 Gate 1 —— subagent 的自我感觉无关紧要。

### 3.4 Token 策略

| 位置 | 策略 |
|---|---|
| 静态上下文 | system prompt（§3.2 的 Goal/权威数据部分）保持逐轮字节一致，并标记 `cache_control: {"type": "ephemeral"}`——若 DeepSeek 端点支持 prompt caching，第 2 轮起系统段几乎免费；不支持则无副作用 |
| 输入瘦身 | 不贴文件；`list_dir` 对 GeoJSON 只列文件名与大小；反馈按 fingerprint 去重、每项截断 evidence 至 500 字符；历史只留 3 轮 |
| 输出上限 | subagent 调用 `max_tokens=32_000`、超时 15 分钟；工具轮次 ≤20 |
| 成本核算 | 每轮记录 `cost.jsonl`（input/output tokens × 单价）；累计超预算（默认 $5，可配）→ `escalate()` |
| 总闸 | `MAX_ROUNDS=10` 封顶；panel 每次运行 7 次调用，因此 panel 轮次严格受总轮数约束 |

### 3.5 图纸（figures）策略

- 生成路径：subagent 用 `run_python` + matplotlib/PIL 生成/重绘 5 张必交图——技术图解、指标仪表盘、网络图风格与 `visual_style_recommendations.json` 推荐一致，且天然可复算（数据来自 GeoJSON/metrics，符合「权威依据是 GeoJSON/metrics，图纸是解释层」的项目规则）。
- 评审路径：judge 5 需要看图。若 DeepSeek 端点支持图像输入，Master 把 5 张 PNG 作为 image content block 附加；**不支持则降级**：judge 5 只收「图的存在性、尺寸、alt 文本、visual_review.py 的确定性检查结果」，并跳过图面判断——因 `figure_quality.default_to_reject=false`，降级不阻断通过，最终由人工评审兜底（与项目现状一致）。

---

## 4. Judge Prompt 复用（Reflection Panel 嵌入）

### 4.1 嵌入方式：prompt 原样 + 证据注入

`judge-prompts/01-07-*.md` **一字不改**地作为每个 judge 调用的 system prompt。Master 只做两件事：

1. **证据注入**：按映射表把 judge 需要的物理文件内容作为 user 消息中的文件块（`"证据文件: <path>\n```...```"`）附加，图像用 image block（若支持）。
2. **确定性预检注入**：延续各 prompt 已有的「CODE PRECHECK 不要重复检查」模式——Master 先算好，直接在 system 前追加一段 `## 确定性预检结果（已由 Master 计算，直接采信，不要重算）`：哈希一致性、面积/比率复算、章节字数统计、keyword 扫描结果等。**LLM 法官不做算术与哈希**，只做语义判断。

证据映射表（按各 statute 的 `physical_evidence` 定义）：

| Judge | 注入的证据文件 | Master 预检注入 |
|---|---|---|
| 01 package_integrity | manifest.json、self_check.json、文件清单 | 全部 SHA-256 对比结果、package_state |
| 02 spatial_quality | geometry/ 全部 8 个图层 | engine 拓扑检查结果（哪些已 PASS，让法官聚焦引擎没覆盖的语义）|
| 03 proposal_depth | proposal.md | 每章正文字数、引用格式命中数、5 图嵌入位置 |
| 04 task_coverage | compliance_matrix.json、proposal.md | requirement 覆盖 diff（与 22+ 条必答 ID 对比）|
| 05 figure_quality | 5 张 PNG（图像块，若支持）+ 各图 alt/来源文本 | visual_review.py 输出（尺寸、>10KB、非纯色块）|
| 06 metric_verifiability | metrics.json、相关图层面积摘要 | site_area/green_ratio/public_space_ratio 从 GeoJSON 的复算结果 |
| 07 compliance_boundaries | proposal.md、sources.json、assumptions.json、copyright_statement.md | engine 关键词扫描结果（C-TEXT/C-SOURCE 已 PASS 项）|

### 4.2 并行执行与解析

- **并行**：7 个 judge 互相独立，`ThreadPoolExecutor(max_workers=7)` 并发调用；anthropic SDK 线程安全。单 judge 超时 5 分钟。
- **解析**：解析 OUTPUT CONTRACT JSON（`refuted / blocking / findings[] / evidence_refs[]`）。解析失败或超时 → 按 `default_to_reject` 处理：true → 记 Refuted（fail-closed），false（figure_quality）→ 记 Not Refuted。
- **一致性保护**：每个 judge 的 `refuted` 与 `blocking` 只认 verdict JSON；prompt 尾部那句 `Refuted / Not Refuted` 仅作日志。

### 4.3 聚合与路由（复用 procedure.json）

```
aggregate(verdicts):
  n_refuted  = count(refuted == true)
  n_blocking = count(refuted && blocking != "none")
  if n_blocking > 0    → BLOCKED     # procedure.json: blocking → human_escalation，不自动改
  elif n_refuted == 0  → APPROVED    # ≥5/7 Not Refuted + 0 blocking → completed
  else                 → NEED_WORK   # minor_fixes(1-2 refuted) 与 major_fixes(≥3) 合并
```

（路由规则取自 `procedure.json.routing_rules`；`minor_fixes` 与 `major_fixes` 在 Goal-Driven 循环里**合并为同一动作**——把 findings 喂给 subagent，改多少由它决定，这正是移除 FSM 后自然的简化。）

- 反馈生成：只收集 refuted 法官的 `findings[]`，跨法官去重（按 location 近似），每法官最多取 5 条、按 severity 排序——下一轮 subagent 的反馈保持小体积。
- Judge 1（package_integrity）在 Gate 1b 通过后理论必过；若它 refuted，说明收尾环节有 bug，计入 escalate 条件。

---

## 5. 实施计划

### 5.1 新增文件

| 文件 | 职责 | 规模估计 |
|---|---|---|
| `scripts/goal_driven_loop.py` | Master 主循环（§2.2 伪代码）、状态管理、stall/预算/升级、`--resume`/`--human-note`/`--max-rounds`/`--dry-run` CLI | ~300 行 |
| `scripts/llm_client.py` | anthropic SDK 封装：env 配置（`ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` / `HAIDIAN_GEN_MODEL=deepseek-v4-pro` / `HAIDIAN_JUDGE_MODEL`）、重试、超时、token/费用日志、cache_control 标记、tool-use 循环 | ~120 行 |
| `scripts/submission_tools.py` | 四工具实现：白名单校验、原子写入、JSON 预校验、run_python 沙箱（subprocess + 超时 + 禁网） | ~150 行 |
| `scripts/panel_runner.py` | judge 证据打包（§4.1 映射表）、7 路并行、verdict 解析与聚合（§4.3） | ~180 行 |
| `docs/goal-driven-entry.md` | 本设计文档 | — |
| `.gitignore` 追加 | `.goal-driven/` | — |

### 5.2 修改文件

| 文件 | 改动 |
|---|---|
| `scripts/finalize_submission.py` | 把 main 逻辑提取为 `finalize_package(submission_dir, require_scaffold=False)` 库函数（循环每轮重收尾用）；CLI 保持原行为 |
| `requirements-review.txt` | 追加 `anthropic>=0.40`；`matplotlib`（run_python 生成图纸，标注可选）|

### 5.3 里程碑

| 里程碑 | 验收标准 |
|---|---|
| **M1：Gate 1 闭环** | scaffold → DeepSeek subagent 首轮改造 → `engine.validate()` 全 PASS → `finalize_package()` 通过（`ready_for_review`）。此时提交包已无占位内容 |
| **M2：Panel 闭环** | 7 judge 并行跑通、verdict 聚合正确；NEED_WORK → subagent 修复 → 再入 Gate 1 → 二轮 panel 收敛 |
| **M3：完整 run** | 一次真实提交跑到 DONE；stall / BLOCKED / 预算超支三条升级路径各有一次演练；`--resume` 验证 |

### 5.4 风险与已知问题

| 风险 | 影响 | 对策 |
|---|---|---|
| DeepSeek 端点 tool-use 不兼容 | subagent 无法工作 | Plan B：结构化输出契约（§3.1），同 prompt 换传输层 |
| DeepSeek 端点不支持图像输入 | judge 5 无法看图 | 降级为证据模式 + `default_to_reject=false` 不阻断 + 人工兜底（§3.5）|
| prompt caching 不生效 | panel 7 次调用成本升高 | 依赖 per-judge 最小证据包 + `MAX_ROUNDS` 封顶；DeepSeek 单价低，可接受 |
| 空间约束收敛慢（面积/拓扑） | 循环空转烧 token | `run_python` 是收敛关键路径；stall 检测 + 历史上下文兜底 |
| finalize 状态机约束（需 scaffold 态） | 循环重收尾失败 | §5.2 的 `require_scaffold=False` 改造，必做 |
| 三区三线判定状态机（urban-design-knowledge 项目）| 生态红线/基本农田/城镇开发边界未建模 | **Gate 1 的扩展点**：状态机封装为一个新的 CODE check 函数 + registry 条目（数据驱动，不改循环结构）；列为 M3 之后的增强，不进 v1 |

### 5.5 明确不做的事（防过度设计）

- ❌ 不建 Phase / FSM / 状态机（`constraints/orchestrator.py`、`run_pipeline.py` 保持原样，`review-panel/master-prompt.md` 作为 FSM 变体文档保留，不修改）；
- ❌ 不给 subagent 传「阶段任务书」或「must_produce 清单」——只有验证失败反馈；
- ❌ 不写任何"生成器"——方案内容全部由 subagent 在运行时产出；
- ❌ 不做并行多 subagent / 子任务分解——一个 subagent 负责全部，简单优先。

---

## 附录 A：关键接口速查

```python
# ConstraintEngine（constraints/engine.py）
ConstraintEngine(repo_root).load_registry()          # → None（或抛 FileNotFoundError）
engine.validate("submissions/<login>/<slug>")        # → list[ConstraintResult]
engine.report(results)                               # → {all_code_checks_pass, critical_failures,
                                                     #    ready_for_llm_review, failures_by_*, results[]}
ConstraintResult: constraint_id, name, outcome, severity, category,
                  detail, evidence, check_type, elapsed_ms, fingerprint
engine.stall_check(cur, prev)                        # → bool（同指纹集合）

# finalize（scripts/finalize_submission.py，改造后）
finalize_package(submission_dir, require_scaffold=False)  # → list[str] 错误列表（空 = 通过）

# panel（scripts/panel_runner.py，新增）
run_panel(submission)                                # → list[JudgeVerdict]
aggregate(verdicts)                                  # → {kind: APPROVED|NEED_WORK|BLOCKED, findings}

# subagent（scripts/llm_client.py + submission_tools.py，新增）
deepseek_work(submission, feedback, history)         # tool-use 循环，直接落盘提交包
```

## 附录 B：环境变量

```
ANTHROPIC_API_KEY=<deepseek key>
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
HAIDIAN_GEN_MODEL=deepseek-v4-pro
HAIDIAN_JUDGE_MODEL=deepseek-v4-pro     # 可单独指定
HAIDIAN_MAX_ROUNDS=10
HAIDIAN_BUDGET_USD=5
```
