# Review Panel for 百年京张AI创新带城市设计

基于 hardlaw 的 Grok Reflection 架构 + Goal-Driven 循环 + Professional FSM，
为 haidian 城市设计开源征集提供四层架构：专业状态机 + 约束引擎 + 反射审查。

## 四层架构

```
┌──────────────────────────────────────────────────────────────┐
│ LAYER 0: Professional FSM (专业城市设计状态机)                 │
│ constraints/procedure.py — 6 Phase 专业工作流 + 15 JUDGMENT   │
│ constraints/domain.py — 专业领域模型                          │
│                                                              │
│ SiteAnalysis → StrategicFramework → DetailedDesign            │
│ → SystemIntegration → Implementation → CompliancePackaging    │
│                                                              │
│ 每个 Phase: CODE steps (确定性) → JUDGMENT (LLM 局部调用)      │
│ → Phase Gate (约束引擎验证转换)                                │
│                                                              │
│ 运行: python3 run_pipeline.py --submission <path>             │
└───────────────┬──────────────────────────────────────────────┘
                │ 每个 Phase 的 CODE exit_checks PASS
                ▼
┌──────────────────────────────────────────────────────────────┐
│ LAYER 0: Constraint Registry                                │
│ constraints/registry.json — 43 条硬约束 (auto-generated)       │
│ 来源: 从 repo 物理文件自动提取 (constraints/extractors.py)      │
│ 动态增减: 编辑 JSON 的 enabled 字段即可                        │
│ 零 LLM 参与                                                  │
└───────────────┬──────────────────────────────────────────────┘
                │ 每次提交自动运行
                ▼
┌──────────────────────────────────────────────────────────────┐
│ LAYER 1: Constraint Engine (constraints/engine.py)           │
│ 确定性执行所有 enabled CODE 约束                               │
│ 输出: [{constraint_id, status, detail, evidence}]            │
│                                                              │
│ spatial (19): 面积容差、图层完整性、拓扑覆盖、枚举值、          │
│               provisional 标记                                │
│ compliance (15): 禁止声明、强制措辞、任务覆盖、来源越级         │
│ metric (9): sanity bounds、面积复算、HTML 一致性               │
│ attributes (9): land_use_code, road_class, building_type 等   │
│ package (5): 文件完整性、图纸要求、HTML 离线                    │
│                                                              │
│ → all_code_pass? → 进入 LLM 审查                              │
│ → critical_failure? → 精确定位错误 → Generator 修复            │
└───────────────┬──────────────────────────────────────────────┘
                │ CODE 全部 PASS 后
                ▼
┌──────────────────────────────────────────────────────────────┐
│ LAYER 2: Reflection Panel (LLM)                              │
│ 只做代码做不到的事:                                            │
│                                                              │
│ Judge 1: package_integrity — 格式完整性                        │
│ Judge 2: spatial_quality — 空间数据质量                        │
│ Judge 3: proposal_depth — 方案文本深度                         │
│ Judge 4: task_coverage — 任务覆盖完整性                        │
│ Judge 5: figure_quality — 图纸专业风格                         │
│ Judge 6: metric_verifiability — 指标可复算性                   │
│ Judge 7: compliance_boundaries — 合规与边界条款                │
│                                                              │
│ 每个 LLM Judge 接收:                                          │
│  1. Layer 0/1 的 CODE 检查结果（已知哪些过了）                   │
│  2. 物理文件本身                                               │
│  3. 只评判硬规则覆盖不到的维度                                   │
└──────────────────────────────────────────────────────────────┘
```

## 设计原则

1. **物理证据驱动** — 每个判断必须引用物理文件（GeoJSON feature、metrics 值、proposal 段落、图片像素），不得基于「感觉好不好」
2. **约束源于数据** — 约束从 repo 物理文件自动提取，数据更新时约束自动更新
3. **Fail-closed** — 不确定时默认拒绝（除 figure_quality 外）
4. **Stall detection** — 同一问题 2 轮修不好 → 人工介入，不无限循环
5. **Law is data, not code** — 评审规则在 JSON 中定义，非程序员可修改

## 文件结构

```
haidian/
├── constraints/                    ← 专业 FSM + 约束引擎 (Layer -1, 0, 1)
│   ├── procedure.py              ← 专业城市设计状态机 (规范)
│   ├── orchestrator.py           ← Goal-Driven 编排器
│   ├── orchestrator.py            ← Goal-Driven + FSM 编排器 (自主循环)
│   ├── __init__.py                 ← 包导出
│   ├── engine.py                  ← Layer 1: 确定性约束引擎 (零 LLM)
│   ├── extractors.py              ← 从 repo 物理文件自动提取约束
│   └── registry.json              ← 43 条约束注册表 (auto-generated, canonical)
│
├── review-panel/                   ← Layer 2: LLM 反射审查
│   ├── README.md                   ← 本文件
│   ├── statutes.json               ← 7 部质量法规 (LLM 评审依据)
│   ├── procedure.json              ← 审查流程状态机
│   ├── master-prompt.md            ← 四层架构总成 (FSM + Engine + Panel + Goal-Driven)
│   └── judge-prompts/
│       01-package-integrity.md      ← 格式完整性法官
│       02-spatial-quality.md        ← 空间数据质量法官
│       03-proposal-depth.md         ← 方案文本深度法官
│       04-task-coverage.md          ← 任务覆盖完整性法官
│       05-figure-quality.md         ← 图纸质量法官
│       06-metric-verifiability.md   ← 指标可复算性法官
│       07-compliance-boundaries.md  ← 合规与边界条款法官
```

## 使用方式

### 1. 生成/更新约束注册表

```bash
# 从 repo 物理文件自动提取所有约束
python3 constraints/extractors.py

# 预览变更 (不写入)
python3 constraints/extractors.py --dry-run

# 查看差异
python3 constraints/extractors.py --diff
```

### 2. 运行约束引擎

```bash
# 对方案包执行全部 CODE 约束
python3 constraints/engine.py submissions/<login>/<slug>

# 仅运行指定约束组
python3 constraints/engine.py submissions/<login>/<slug> --group spatial_topology

# 仅运行 critical 级别约束
python3 constraints/engine.py submissions/<login>/<slug> --severity critical

# JSON 输出 (用于 CI/CD)
python3 constraints/engine.py submissions/<login>/<slug> --json
```

### 3. 启动 Goal-Driven + Reflection Panel

将 `master-prompt.md` 中的模板发送给 Claude Code：

```
# Goal-Driven + Constraint Engine: haidian 城市设计

Goal: 在 submissions/<github-login>/<proposal-slug>/ 下生成完整 formal 方案包

Criteria: constraint_engine all_pass + 7 法官 ≥5/7 Not Refuted

工作目录: /path/to/haidian
请读取 review-panel/master-prompt.md 开始 MASTER LOOP。
```

## 动态增减约束

编辑 `constraints/registry.json`:

```json
// 添加新约束
{
  "constraint_id": "C-CUSTOM-001",
  "group": "custom",
  "name": "my_custom_rule",
  "check_type": "CODE",
  "check_function": "grep_forbidden_patterns",
  "params": {
    "forbidden_patterns": ["禁用词A", "禁用词B"],
    "target_file": "proposal.md"
  },
  "severity": "critical",
  "enabled": true
}

// 禁用某条约束
将 "enabled": true 改为 "enabled": false

// 重新运行提取器时, auto 约束自动更新, manual 约束保留人工修改
python3 constraints/extractors.py
```

不需要改任何 Python 代码或 prompt 文本。

## 约束组一览

| 组 | 数量 | 类型 | 说明 |
|---|---|---|---|
| area_validation | 6 | auto | 面积容差验证 (±5% site, ±10% 其他) |
| coordinate_system | 2 | auto | EPSG:4326 交换, EPSG:4548 计算 |
| required_layers | 4 | auto | 8 必填图层 + 6 锁定图层 + 几何类型 |
| spatial_topology | 6 | manual | 覆盖、无重叠、边界内 |
| feature_attributes | 9 | auto/manual | 枚举值、provisional 标记、必填属性 |
| metric_verification | 7+ | auto/manual | sanity bounds、缺失控规、面积复算 |
| compliance_text | 3 | manual | 禁止措辞、强制措辞、控规缺失 |
| source_integrity | 2 | auto/manual | 来源越级、溯源完整性 |
| compliance_matrix | 1 | auto | 22 条 requirement 全覆盖 |
| design_depth | 1 | auto | 强制性标准引用 |
| professional_standards | 1 | manual | 城市设计管理办法 |
| proposal_structure | 2 | manual | 14 章节 + 5 图嵌入 |
| figure_requirements | 1 | manual | 5 PNG >10KB |
| html_visualization | 2 | manual | 离线 + data-metric |
| agent_task_requirements | 7 | auto/manual | 6 任务 + 章程原则 |
| physical_site_constraints | 2 | auto/manual | 海淀坐标 bounds + 精度声明 |
| package_structure | 1 | manual | 30 文件完整性 |

## 与 haidian 项目的关系

| 项目自带的 | Review Panel 补充的 |
|---|---|
| `self_check_submission.py` — 格式/拓扑验证 | 61 条硬约束引擎 (零 LLM 成本) |
| `ai_review_submission.py` — 可选 AI 评分 | 7 维度独立法官 + 物理证据交叉验证 |
| `maintainer_review.py` — 维护者人工审查 | 提交前的自动化质量门禁，减少人工审查负担 |

## 修改评审标准

- **硬约束**: 编辑 `constraints/registry.json` 或重新运行 `constraints/extractors.py`
- **LLM 评审**: 编辑 `statutes.json` — 不需要改任何代码
- **流程**: 编辑 `procedure.json` — 调整状态机路由规则

每条 statute 包含：
- `pass_condition`: 通过条件（人类可读）
- `violations`: 违规类型列表，每条含 `severity` 和 `detection`（如何发现）
- `physical_evidence`: 必须检查的物理文件清单
- `default_to_reject`: 不确定时是否拒绝
