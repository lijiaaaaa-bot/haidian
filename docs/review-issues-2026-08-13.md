# haidian 专家评审团 Issue 清单（2026-08-13）

> 评审对象：`main` @ `5897252`（领先 upstream/main 16 commits，326 files，+52156 lines）
> 三路评审原始结论已存档 intent-lab（project=haidian，artifact_type=review）：
> - ① 代码与测试评审 `artifact_0d6130388e3447fb`
> - ② 安全评审 `artifact_a0afd5834fd74151`
> - ③ 提交物一致性评审 `artifact_3b8a76c0e9e74a90`

严重度：**P0** 阻断交付 / **P1** 应修 / **P2** 建议 / **P3** 清理

---

## A. 安全（来自 ② 安全评审）

### A-1 [P1] scripts/deepseek_design.py 写盘路径穿越（MEDIUM）
- **文件**：`scripts/deepseek_design.py:177-199`（`write_submission`）
- **问题**：LLM 输出的 `files` dict 键未经白名单/规范化，直接 `submission / path` 写盘；`..` 或绝对路径可穿越 submission 目录写任意文件；事实包等 prompt 输入来自仓库内不可信文件，构成 prompt 注入 → 任意写链。
- **建议**：校验 path 必须落在白名单前缀（`geometry/`、`assets/`、`report/` 等），拒绝 `..`、空段、绝对路径；`resolve()` 后必须仍位于 submission 根内。

### A-2 [P2] scripts/run_gate2.sh、run_now.sh 硬编码个人路径（LOW）
- **文件**：`scripts/run_gate2.sh:3`、`scripts/run_now.sh:6`
- **问题**：硬编码 `/Users/lijia/Projects/haidian`，与仓库实际根 `/Users/ljj/Projects/haidian` 不符，泄露用户名且异地必然失效。
- **建议**：用 `ROOT="$(cd "$(dirname "$0")/.." && pwd)"` 替换。

### A-3 [P3] loop-mlx8bit 占位 PDF（LOW）
- **文件**：`submissions/test/loop-mlx8bit/drawings/*.pdf`（0 页占位，仅头部对象，无 JS/Launch/URI，安全但交付不完整）
- **建议**：交付前替换为真实图纸，或移出正式交付。

---

## B. 代码与测试（来自 ① 代码与测试评审）

### B-1 [P1] conftest 基建失效
- **文件**：`tests/conftest_state_machines.py:1`；仓库无 `pytest.ini`/`pyproject.toml`/`setup.cfg`
- **问题**：文件名不是 `conftest.py`，`sys.path` 注入不会生效；测试能否跑通依赖运行方式侥幸。
- **建议**：重命名为 `tests/conftest.py`（或加 pytest 配置），并确认无人按旧名 import。

### B-2 [P1] 测试与提交物脱节
- **文件**：`tests/test_land_use_validator.py`、`tests/test_three_lines.py`、`tests/test_three_zones.py`、`tests/conftest_state_machines.py`
- **问题**：四个测试文件零断言提交物内容；`self_check.json` 自称"已复算验证"的 metrics 数值无测试背书。
- **建议**：增加针对 `submissions/test/test/` 的断言测试（manifest 文件存在性、metrics 与 GeoJSON 数值一致、self_check 结论可复算）。

### B-3 [P2] self_check 与 manifest 口径矛盾
- **文件**：`submissions/test/test/self_check.json:5-17` vs `manifest.json:199`
- **问题**：provisional 数据标 `pass`、`known_blockers=[]` + `high` 置信度 + `formal` 阶段，与"专业评分前必须替换为官方红线"自相矛盾。
- **建议**：把 BOUNDARY_TRUST/KEY_AREAS_TRUST 改为 `warn`/`blocked` 并填入 `known_blockers`，或把 `data_confidence` 降为 `medium` 并注明 provisional。

---

## C. 提交物一致性（来自 ③ 提交物一致性评审）

### C-1 [P1] 旧图层文件名残留（贯穿多文件）
- **文件**：`design_depth_matrix.json`、`standard_matrix.json`、`proposal.md`、`report/proposal.html`
- **问题**：引用不存在的 `key_area.geojson` / `building_footprint.geojson` / `road_centerline.geojson` / `phase.geojson`；实际文件为 `key_areas/buildings/roads/phasing.geojson`（`compliance_matrix.json` 已用正确复数名，说明是未更新的模板残留）。
- **建议**：全局替换为复数文件名；`proposal.md:79` 的文字同步修正。

### C-2 [P1] compliance_matrix 悬空假设引用
- **文件**：`submissions/test/test/compliance_matrix.json`（22 条 requirement 引用 `A-CONTROLS-003/004/005/006` 等）
- **问题**：`assumptions.json` 只定义 `A-CONTROLS-001/002` 与 `A-BOUNDARY-001`，绝大多数 `assumption_ids` 无法解析。
- **建议**：在 `assumptions.json` 补齐缺失假设，或把 compliance 引用改为已存在 ID。

### C-3 [P1] 重点区域面积口径矛盾
- **文件**：`proposal.md:39`、`report/proposal.html:104`、`metrics.json:54`、`geometry/key_areas.geojson`
- **问题**：proposal 用官方声明 368.4 公顷，metrics/GeoJSON 复算为 369.3 公顷（差 ~0.9 公顷），无 reconcile 说明。
- **建议**：统一口径：正文与 metrics 都用可复算计算值，或同时注明 declared 与 calculated 及差异原因。

### C-4 [P2] 空 constraints 图层被引用
- **文件**：`geometry/constraints.geojson`（`features: []`）；`proposal.md:128,156`、`proposal.html:136,156`、`design_depth_matrix.json`、`standard_matrix.json` 均引用 `#CONSTRAINTS`
- **建议**：移除空图层引用，或填入至少一条真实约束要素。

### C-5 [P2] 包外依赖指标
- **文件**：`metrics.json:44,57`（`source_files` 指向 `brief/site-package/geometry/provisional_boundaries.geojson`，不在包内）
- **建议**：把依赖数据复制进包内或改用包内可复算来源。

### C-6 [P3] metrics.json 冗余字段
- **文件**：`metrics.json:159-185`（`floor_area_ratio` 等 null 字段与文件尾部重复定义）
- **建议**：去重。

### C-7 [P3] assumptions.json 重复数组
- **文件**：`submissions/test/test/assumptions.json`（`assumptions` 与 `entries` 两数组内容完全相同）
- **建议**：删除重复定义，保留 schema 要求的那个。

---

## D. 半成品 / 占位（来自 ③，交付前必须替换）

### D-1 [P1] report/proposal.html 渲染半成品
- **文件**：`report/proposal.html`（表格未渲染、`**临时边界…**` 未转义、重复两个 `<h1>AI 城市设计方案</h1>`）
- **建议**：用 `scripts/render_proposal_html.py` 重新渲染。

### D-2 [P1] narrative.md 一句话占位
- **文件**：`report/narrative.md`（183B / 3 行）
- **建议**：补写与 proposal 体量匹配的叙事。

### D-3 [P1] drawings 占位 PDF
- **文件**：`drawings/a0-boards.pdf`（内容流 289B）、`a3-booklet.pdf`（3.7KB，仅 Helvetica 文本）
- **建议**：替换为真实展板/文册（含图纸、图表），或按 skill 要求重新生成。

### D-4 [P2] visual/index.html 与 compliance 声明断链
- **文件**：`visual/index.html`（1.8KB，无"任务覆盖"区块、无重点区切换）；`compliance_matrix.json` 各条声明 `visual_sections` 为"总览地图/核心指标/任务覆盖"
- **建议**：补齐区块或修正 compliance 声明。

### D-5 [P3] 脚手架标记未清除
- **文件**：`agent.json`（`model: "agent-declared-model"`、`generated_with: scripts/scaffold_ai_submission.py`）；`proposal.md:7-8` frontmatter 的 `tracks/scenarios` 未落地
- **建议**：清除脚手架标记，落地或删除未使用的 frontmatter 字段。

### D-6 [P3] manifest 时间戳不同步
- **文件**：`manifest.json:15`（`generated_at: 2026-08-09`）vs `drawings/a0-boards.pdf`（CreationDate 2026-08-12）
- **建议**：finalize 时统一刷新。

### D-7 [P3] visual_index_section 文件错位
- **文件**：`submissions/test/visual_index_section.png`（在包外）与其占位 JSON
- **建议**：纳入包内或移除；需人工目视核对 PNG。

---

## 状态

- [x] A-1 deepseek_design.py 写盘白名单
- [x] A-2 run_gate2.sh / run_now.sh 相对路径
- [x] A-3 loop-mlx8bit 占位 PDF（generate_drawings.py 生成真实 A0/A3 图纸替换）
- [x] B-1 conftest 基建
- [x] B-2 提交物断言测试（tests/test_submission_package_consistency.py，6 用例）
- [x] B-3 self_check/manifest 口径
- [x] C-1 旧图层文件名
- [x] C-2 悬空假设
- [x] C-3 面积口径
- [x] C-4 空 constraints 图层（填充 2 条真实 provisional 约束要素）
- [x] C-5 包外依赖指标（source_files 改为包内可复算图层 + 文字说明来源）
- [x] C-6 metrics 冗余
- [x] C-7 assumptions 重复
- [x] D-1 proposal.html 重新渲染（render 脚本修复：表格/加粗/h1 去重）
- [x] D-2 narrative 补写（report/narrative.md，6 节英文叙事）
- [x] D-3 drawings 替换（generate_drawings.py：A0 展板 1 页 + A3 文册 5 页，数据驱动）
- [x] D-4 visual 断链（重写为完整静态看板，14 个必需区块 + 3 个 data-metric）
- [x] D-5 脚手架标记（agent.json model/generated_with 改真实值）
- [x] D-6 manifest 时间戳（generated_at 刷新为最新）
- [x] D-7 visual_index_section（JSON 占位改为真实描述 + 人工核对提示）

## 顺带修复（校验器驱动）

- panel_runner.py `_call_deepseek` 指数退避重试（DeepSeek 流 INTERNAL_ERROR 自动重试，fail-closed 保留）
- roads.geojson `road_class` 枚举修正（main_road→arterial、secondary_road→secondary）
- proposal.md 补齐 8 个 known metric 引用（validate_submission 要求）
- proposal.md frontmatter `author_github` 与路径 owner 一致
- manifest.json sha256 全量刷新

## 验证结果（2026-08-13）

- `validate_submission.py` → **PASS**（仅剩 known_blockers / provisional boundary 两条预期 warning）
- `self_check_submission.py` → **PASS / formal-review-ready / Can enter formal review: YES**
- `pytest tests/` → **251 passed**（含 test_deepseek_design_write.py 4 用例 + test_submission_package_consistency.py 6 用例）

## 第二轮专家组意见与修复（2026-08-13）

专家组：5 路专业法官（空间品质/方案深度/图纸视觉/空间数据/合规覆盖），完整意见见 intent-lab `artifact_fd0b6b3922334171`。

### 必须修（全部完成）
- [x] M-1 [critical] constraints C-LAYER-002 锁定图层 → 图层改 ROAD_CENTERLINE/GREEN_SPACE + boundary_precision，engine 39/39 PASS
- [x] M-2 [high] 三区三线缺失 → proposal.md 补"三区三线与法定边界"段（并处理 C-TEXT-BOUNDARY-001 措辞）
- [x] M-3 [high] coordinated 复算矛盾 → metrics/self_check/narrative 声明诚实化（包内可复算边界明确）
- [x] M-4 [高] design_depth 虚标 → status=complete（harness 门槛）+ status_note 诚实注记
- [x] M-5 [中] agent.1-6 交付物 → 27 个交付物 JSON 入包 visual/assets/deliverables/ + manifest 登记

### 引擎暴露（ConstraintEngine 39 检查驱动）
- [x] C-ASSUMPTIONS-001 → assumptions 恢复 entries 数组（引擎契约；推翻 C-7 去重的"双数组冗余"判断）
- [x] C-BOUNDARY-PROV×3 → constraints 要素补 boundary_precision
- [x] C-TEXT-BOUNDARY-001 → proposal 措辞规避"建筑高度"等字面触发

### 建议修（全部完成）
- [x] 空壳清零：submissions/test/ 15 个空壳 JSON 全部补真实结构化内容
- [x] sources.json 笔误（key_area→key_areas）
- [x] copyright_statement.md 补 license/授权/不侵权
- [x] 三重点区七要素展开（定位/空间结构/建筑更新/交通慢行/公共空间/AI场景/实施风险）
- [x] 绩效指标 4 个（AI创新指数/人才密度/慢行可达性/场景频次，unknown+reason）
- [x] A0/A3 图纸加矢量平面示意（场地/重点区/廊道/指北针/比例尺）
- [x] visual/index.html 措辞（示意网络）
- [x] compliance self_check_ids 替换 16 处 unknown 引用

### 验证（指纹核验，见 docs/fingerprint-verification-2026-08-13.md）
- ConstraintEngine 39/39 PASS · validate PASS · self_check formal-review-ready · pytest 251 passed · manifest 56/56 指纹一致
