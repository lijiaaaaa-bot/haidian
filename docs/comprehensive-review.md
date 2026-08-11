# haidian 项目体系综合评审报告

**评审人**：专家组（专家组组长综合）
**日期**：2026-08-11
**范围**：haidian 本体（Goal-Driven 循环 + 39 条 CODE 约束 + 7 审委 Panel + 双模型 subagent）+ 两个子项目（urban-design-knowledge / urban-spatial-tooling）
**方法**：只读审查。逐文件读取 `scripts/goal_driven_loop.py`、`constraints/engine.py`、`constraints/registry.json`、`constraints/state_machine_checks.py`、`constraints/state_machines/*`（4 模块）、`scripts/panel_runner.py`、`scripts/run_autonomous.sh`、`review-panel/*`；对照 `docs/final-submission-review.md`（8/11，4/10）与 `docs/local-model-evaluation.md`（8/9）；核查两子项目实际交付（知识库 7 笔记 + 4 模块 + 68 测试；工具库 21 notebook + 17 模块 + 117 测试）；grep 验证集成点与死代码。未改动任何文件。

---

## 〇、结论摘要

| 项 | 结论 |
|---|---|
| haidian 本体 | **工程架构良好，验证器成熟度高于产出物成熟度**。循环、双模型路由、沙箱、崩溃恢复均已工程化；但"ratchet 未接线""Master 不 finalize""Gate 2 默认不开 Panel"三个结构性缺口，使循环的"成功"（Gate 1+Gate 2 PASS）无法转化为"可提交"（maintainer 门禁 FAIL，评分 4/10） |
| urban-design-knowledge | 状态机已移植并接线（68 测试、6 条 C-SM 检查），但 **3/4 的领域深度未用**：three_zones 零接线、judge_land_use 导入了没用、海绵/生活圈/更新笔记未转检查 |
| urban-spatial-tooling | **零集成**。pipeline.py 自述"供 haidian procedure.py 使用"但 grep 无任何对接；generation/visualization 正是 P0"几何/图纸占位"的现成解药，价值被完全搁置 |
| 综合判断 | 系统"跑得动、检得严、产不出好方案"。距可生产使用：**harness 侧差 1-2 个迭代轮，产出侧差 3-4 个迭代轮**（先补契约闭环，再补技术分析深度，最后补概念创意层） |

---

## 一、haidian 本体综合评分表

| # | 维度 | 得分 | 一句话结论 |
|---|------|------|-----------|
| a | 架构设计 | **7/10** | lidangzzz 模式 + 双模型路由 + 会话复用 + 停滞检测是合理的；但 ratchet 是死代码（快照函数从未被调用），循环完成态 ≠ 可提交态 |
| b | 约束覆盖 | **7/10** | 39 条 CODE 覆盖空间完整性/合规边界/指标合理性扎实（面积缺键已从"回退"修为"FAIL"，图层命名三处门禁已统一）；但设计质量与领域深度欠账：三区三线仅关键词级、状态机判词未用、零技术分析检查 |
| c | 质量评审 | **6/10** | 7 审委 Panel 工程优良（并行、fail-closed、证据预算、视觉模型看图）；但默认未启用（--panel 开关）、审委模型与产出模型同级（判别力有限）、heuristic Gate 2 可被指纹绕过 |
| d | 稳定性 | **7/10** | 八重恢复机制（健康检查/重试/备用模型切换/失败计数持久化/监督重启/Ollama 硬重启/MAX_HOURS/会话重置）已工程化；沙箱已补写向量（P0 已修）；但 subprocess 逃逸未堵、崩溃时无状态检查点 |
| e | 可扩展性 | **8/10** | 注册表驱动，新检查 = registry 加条目 + engine 注册一个纯函数；参数是数据，manual_overrides 可调；状态机检查即插即用；最成熟的一项 |
| f | 整体成熟度 | **5/10** | 循环本体接近可无人值守；但历次运行最优产出 4/10、门禁 request-changes、图纸几何仍是占位。"DONE"离"可提交"还有 P0 四件事的差距 |
| | **加权综合** | **6.5/10** | 一套认真的自治系统，卡在"验收标准测的是契约合规，不是设计实质" |

---

## 二、逐维度评价与证据

### a) 架构设计 — 7/10

**合理部分（成立）**：
- Master 三职责（建 subagent、查存活、验 Criteria）与 lidangzzz 模式一致；subagent 自己读仓库状态决定改什么——8/9 实测一轮 18→0 证明此闭环有效。
- 双模型路由 `_pick_model`（coder 处理 spatial/metric/attributes/package 类失败，writer 处理 compliance 类，混合时交替）是真改进，而非噱头。
- 会话级消息复用 + 只注入本轮失败明细（`inject`），把输入从 DeepSeek 版的 10-30M token 压到 0.5-2M（14 倍时间加速）。
- 停滞检测（3 轮相同失败集 → 重置会话）防止空转。

**关键缺口（扣分）**：
- **G-1 ratchet 未接线（架构声称的三件套缺一件）**：`_save_snapshot`/`_restore_snapshot`（`goal_driven_loop.py:678-695`）定义完整但 `main()` 中**零调用**。8/9 实测的自伤性回退（删 4 个规范名文件、丢 entries 键、丢 4 个面积键）正是 ratchet 该拦截的场景——它没有发挥作用。`.goal-driven/snapshots/` 目录从未建立。
- **G-2 Master 不 finalize（"收尾时统一刷新"从未发生）**：`SYSTEM_PROMPT` 与 `_handle_write_file` 均禁止 subagent 改 manifest.json，理由是"Master 收尾时统一刷新"；但 `main()` 在 Gate 2 PASS 后直接 `return 0`，**没有任何 manifest 重生成 / self_check 重跑 / finalize_submission.py 调用**。这解释了 8/11 评审中持续存在的"10 处 manifest 哈希失配"与"self_check 声称全绿但实测 15 FAIL"——循环的成功路径根本不刷新这两个文件。
- **G-3 验收目标分裂**：循环优化的是 `engine.validate()`（39 CODE）+ Gate 2；真正的收件门禁是 `maintainer_review.py`（哈希/白名单/PDF 页数/作者一致性）。8/9 的本地模型就是因为同时响应两套互相矛盾的门禁才自伤。循环从未把 maintainer 门禁纳入 Criteria。

### b) 约束覆盖 — 7/10

**已覆盖（扎实）**：
- 空间完整性：必交图层（LAYER-001，且已与 maintainer 门禁统一命名，`MAINTAINER_GEOMETRY_FILENAMES` 消除"必须交又不许标"矛盾）、越界（GEO-001）、覆盖（GEO-002）、重叠（GEO-003）、枚举（ENUM×3）、provisional 标记（BOUNDARY-PROV×3）、锁定图层（LAYER-002，SITE_BOUNDARY/KEY_AREA 已豁免）。
- 合规边界：六项 agent 任务覆盖（TASK×6，兼容 entries/requirements 双键——8/9 契约错位已修）、禁止性声明（TEXT-FORBIDDEN + BOUNDARY-001）、强制措辞（BOUNDARY-002）、来源越级（SOURCE-001）、缺失控规记录（ASSUMPTIONS-001）。
- 指标合理性：面积容差 ×6（**缺键已修为显式 FAIL**，不再回退第一个值——8/9 P0 已修）、sanity 界限 ×3、EPSG:4548 引用。
- 状态机六条（C-SM-*）：几何有效（环闭合按原始坐标判，防 shapely 自动闭环）、高度字段、路网 ≥3、绿地率**用几何实测不读声明值**——这几条专治"脚手架占位"。

**缺口（扣分）**：
- **G-4 状态机只用了表面**：`C-SM-LANDUSE` 导入了 `LandUseOrchestrator/judge_land_use`（`state_machine_checks.py:21-25`）但检查本体只做枚举集合成员判断（`_load_land_use_codes`）——68 测试里的地带归属判词（如"农业地类不得出现在城镇开发边界内"）完全没有发挥作用。`three_zones.py`（29KB 状态机）**在 registry 中无任何条目**。`C-SM-THREELINES` 是关键词 grep（附带"国土空间"宽松豁免），非几何校验。
- **G-5 零技术分析检查**：日照、海绵、生活圈、退线、视廊、交通承载力——全部在兄弟项目里有现成实现（spatial-tooling 14 个专项分析模块 + 117 测试），registry 中一个都没有。专业评审（8/7）判词"零技术分析"在约束层依旧成立。
- **G-6 内容质量只能靠 Gate 2 启发式**：39 条 CODE 全是契约性检查。"深度矩阵 15 项 complete 而图纸为空"这类声明-交付断裂，CODE 层无感知。Gate 2 的模板套话/整跨矩形/占位图指纹启发式是补救，但可绕过（8/11 的 32 PASS 0 FAIL 包内容分 4/10 就是证据）。

### c) 质量评审（Gate 2 Panel）— 6/10

**工程优良**：
- 7 审委并行（`ThreadPoolExecutor(max_workers=7)`）、fail-closed（超时/解析失败 → default_to_reject）、每审委独立证据预算（`EVIDENCE_PLAN` 按实测 prefill 速度定预算）、figure_quality 走视觉模型（qwen2.5vl）+ base64 图片、JSON 证据保结构压缩（`_compact_json`）、聚合规则明确（≥5/7 Not Refuted + 0 blocking → APPROVED，`procedure.json` 同）。
- 七条 statute 全部要求"物理可验证产出物"（`review-panel/statutes.json`），package_integrity 审委直接核对 manifest 哈希与 self_check——若启用，8/11 的哈希失配会当场被抓。

**扣分**：
- **G-7 Panel 默认不启用**：`--panel` 标志或 `HAIDIAN_PANEL=true` 才开启，默认走启发式 stub。8/9、8/11 两次正式评审均未运行 Panel，其能力未在任何真实评审中被验证过。
- 审委模型（qwen3.6:35b-a3b）与产出模型同级甚至同款——"用写手审写手"。判别力上限受模型约束（本地模型叙事厚度本就不足）。
- 启发式 Gate 2 的占位检测是**指纹式**（78,378 字节、1640×840 脚手架配色、纯色 >80%），换一种模板即可绕过；PDF 页数/白占比检查在 Gate 2 中缺失（8/11 的 0 页 PDF 未触发）。

### d) 稳定性 — 7/10

**已工程化（八重）**：
1. `_ollama_health_check`：死服务不挂起，限次后抛错触发监督重启；
2. HTTP 5xx/超时重试 3 次；
3. 连续失败 ≥3 次切换备用模型（coder↔writer），计数持久化到 `.goal-driven/model-failures.json`（重启后新进程给一次新生机会）；
4. `run_autonomous.sh` 监督循环：崩溃 → `pkill -9 ollama` → 重启 → 重跑，日志保留 10 份；
5. MAX_HOURS=12 上限；
6. 停滞检测重置会话；
7. `_warmup_model` 预载模型；
8. **run_python 写沙箱已补全**（8/9 P0 已修）：prologue 包装 open/remove/unlink/rename/replace/write_text/write_bytes，与 write_file 同策略。

**残余风险**：
- **G-8 subprocess 逃逸未堵**：沙箱 prologue 不拦 `subprocess`/`os.system`/`ctypes`。子进程不继承 prologue，`subprocess.run(["python3","-c","open('x','w')..."])` 可绕过全部写限制。8/9 报告"DeepSeek 的作弊路径仍然开着"，本轮修复后主向量已堵，但逃逸向量仍在。无网络缓解了大部分危害，但文件系统写入已足够造成破坏。
- 崩溃恢复无状态检查点：会话消息存内存，进程级崩溃即丢；快照机制（本可做检查点）未启用。
- 30s run_python 超时：对重计算（如批量 GPU 投影）不友好——不过 spatial-tooling 已判定生产路径 CPU-only，此约束可接受。

### e) 可扩展性 — 8/10

- 注册表驱动是硬设计：新增检查 = `registry.json` 加条目（check_function/params/severity 全是数据）+ `engine._register_builtins` 注册一个纯函数，`engine.validate` 自动执行。无需改循环。
- `params` 参数化（如 `min_roads`、`height_fields`、`valid_layers`）让同一检查函数可复用多场景；`manual_overrides` 支持不动生成器的手动调优。
- `extractors.py` 从 brief 数据文件自动生成 registry，与任务书保持同步（8/9 曾因手改冲突，现为生成 + overrides 双源）。
- 状态机检查的接入路径（wrapper 转发到 `constraints/state_machine_checks.py`）证明"外部知识 → 确定性检查"的流水线已打通——knowledge 项目的剩余模块可照此接入。
- 扣分点：检查函数注册在 `engine.py` 内硬编码（新增需改代码文件，虽小）；`extractors.py --generate` 与手动注册的并集关系没有一致性测试。

### f) 整体成熟度 — 5/10

**距"可生产使用"的差距**（按距离排序）：
1. **契约闭环**（1 轮迭代）：Master finalize（manifest/self_check 刷新）+ ratchet 接线 + 三套门禁（CODE/maintainer/panel）统一为单一验收函数 + subprocess 堵漏。修完，循环的"成功"才等于"可提交"。
2. **产出真实化**（1-2 轮）：接入 spatial-tooling 的 generation/visualization 作为 subagent 工具，把 4 条竖条带/3 个矩形/1 条直线/PIL 五胞胎图全部替换为真实几何与专业图纸——8/11 评审的 P0 四项。
3. **领域深度**（2-3 轮）：C-TECH-* 技术分析检查入 Gate 1、状态机深度接线（three_zones + judge_land_use）、数据门控（三区三线/视廊官方数据 NOT_ASSESSED 语义）。
4. **概念创意层**（空缺，M5+）：品牌/叙事/场景卡全格式生成是"LLM 原生能力"层面，harness 只提供模板与验证，需要单独建设。

**判断**：循环本身已可无人值守跑 12 小时；但产出物从未越过 4/10。"可生产使用"的定义若是"产出可提交的方案包"，当前差 3-4 个迭代轮；若是"自治系统稳定运行"，已基本达成。

---

## 三、缺口分析清单

| 编号 | 缺口 | 证据 | 影响 | 优先级 |
|---|---|---|---|---|
| G-1 | ratchet 死代码：快照函数零调用 | `goal_driven_loop.py:678-695` 定义、`main()` 无调用；`.goal-driven/snapshots/` 不存在 | 自伤性回退无法回滚（8/9 实测发生 3 次） | P0 |
| G-2 | Master 不 finalize：禁改 manifest 却无人刷新 | `SYSTEM_PROMPT:107` + `main()` 无 finalize 调用 | 循环 DONE 的包哈希必失配，maintainer 门禁必 FAIL（8/11 实测 10 处失配） | P0 |
| G-3 | 验收目标分裂：循环优化对象 ≠ 收件门禁 | 循环只跑 `engine.validate()`+Gate 2；`maintainer_review.py` 独立 | 模型被互相矛盾的门禁拉扯（8/9 自伤根因） | P0 |
| G-4 | 状态机深度未用：three_zones 零接线、judge_land_use 导入未用、THREELINES 仅关键词级 | `state_machine_checks.py:21-25` 导入未用；registry 无 C-SM-ZONES | 68 测试的能力约一半空转 | P1 |
| G-5 | 零技术分析检查（日照/海绵/生活圈/退线/视廊/交通） | registry 无相关条目；spatial-tooling 有现成实现未接入 | 专业评审"零技术分析"判词持续成立 | P1 |
| G-6 | 声明-交付断裂无 CODE 层感知 | 8/11：深度矩阵 15 项 complete + 图纸 0 页 | "全部声明指向不存在交付"的系统性缺陷 | P0 |
| G-7 | Panel 默认关闭，能力未经真实评审验证 | `main()` 需 `--panel`/env；两次正式评审均未运行 | 质量把关主要靠可绕过的启发式 | P0 |
| G-8 | run_python 沙箱 subprocess 逃逸 | prologue 不包装 subprocess/os.system/ctypes | 沙箱形同虚设于恶意代码（本模型未利用，属侥幸） | P0 |
| G-9 | 两子项目零集成（详见下节） | grep `procedure.py` 无 TechnicalReviewRunner 引用 | 价值最高的两个仓库搁置 | P1 |
| G-10 | 枚举缺陷残留：land_use 0702 与国标不符 | knowledge 笔记 03 已发现；8/11 评审再确认 | 正式提交前的合规地雷 | P1 |

---

## 四、子项目评估

### 4.1 urban-design-knowledge（规划标准层）

**现状**：7 篇笔记（国土空间体系/控规/用地分类/海绵/生活圈/更新/海淀背景）→ 4 个 src 模块（land_use_validator / state_machine / three_lines / three_zones）→ 68 个测试。**已移植**进 haidian `constraints/state_machines/`（commit 1af177d），接线为 6 条 C-SM-* CODE 检查。8/11 前还修复了 land_use_codes.json（商业 05→09）与枚举提取器（a8a7dd3）。

**当前利用度：5/10**
- 已用：C-SM-LANDUSE（代码合法）、C-SM-THREELINES（提及）、C-SM-GEOMETRY-VALID、C-SM-BUILDING-HEIGHT、C-SM-ROAD-NETWORK、C-SM-GREEN-RATIO。
- 未用（约一半能力空转）：
  - **three_zones.py 完全未接线**——生态/农业/城镇三区的判词逻辑没有对应检查；
  - **judge_land_use / LandUseOrchestrator 导入未用**——地带归属一致性（"用地代码 07 落在农业空间"类矛盾）可判未判；
  - 笔记 04 海绵城市、05 生活圈、06 城市更新、07 海淀视廊约束——**未转成任何检查**；
  - 控规五指标（FAR/密度/退线/绿地率/高度）仅高度有字段级检查，FAR/密度/退线无几何复算。

**接入价值：8/10**
- 直接对应专业评审五大缺陷中的三个（三区三线、控规非结构化、零技术分析）与 8/11 评审 P1 第 5-7 条。
- 状态机是纯函数（同输入同输出），与 engine 的零 LLM 设计哲学完全兼容，接入成本 = registry 条目 + wrapper 一行。

**接入清单（按优先级）**：
| # | 接入项 | 来源 | 形态 | 预期效果 |
|---|---|---|---|---|
| K-1 | 地带-代码一致性检查（judge_land_use 真实启用） | `land_use_validator.py` | C-SM-LANDUSE 升级 | 拦截"城镇开发边界内的农业地类"类矛盾，从成员检查升级为判词检查 |
| K-2 | 三区检查 | `three_zones.py` | 新 C-SM-ZONES | 补上"三区"一半（现状只有"三线"关键词级） |
| K-3 | 三线几何校验（数据门控） | `three_lines.py` | 新 C-SM-THREELINES-GEO，缺官方数据报 NOT_ASSESSED | 从"提及"升级为"比对"，借鉴 spatial-tooling 的 NOT_ASSESSED 语义 |
| K-4 | 海绵城市检查（年径流总量控制率 ≥85%，DB11/685-2021） | 笔记 04 + spatial-tooling `sponge.py` | 新 C-TECH-SPONGE（fail-closed） | 技术分析零突破 |
| K-5 | 生活圈配置率检查（TD/T 1062-2021） | 笔记 05 + `living_circle.py` | 新 C-TECH-LIVING-CIRCLE | 同上 |
| K-6 | 拆改留分类一致性 | 笔记 06 + `renewal.py` | 新 C-TECH-RENEWAL | 拦截"深度矩阵自称拆改留 complete 但正文未交付"（G-6 的领域版） |

### 4.2 urban-spatial-tooling（空间计算层）

**现状**：21 个 notebook + 17 个 src 模块（**CLAUDE.md 已过时**：文档写 10 模块，实际另有 adapter/autoresearch/closure/renewal/traffic/ventilation/vertical/integration）+ 117 个测试。GPU 实验（Metal 投影 3-4.5x）已诚实归档为负结果（生产路径 CPU-only），`pipeline.py` 的 TechnicalReviewRunner 带 AND 门 + CRITICAL/MAJOR 阻塞 + NOT_ASSESSED 数据门控语义，自述"供 haidian procedure.py 使用"。

**当前利用度：2/10**
- **零集成**。grep haidian 全仓无 `TechnicalReviewRunner`/`tech_review`/`spatial-tooling` 引用；`procedure.py` 仅一处"考虑海绵城市理念"的空话。
- 数据共用仅 `data/haidian-boundary.geojson`（测试 fixture 级）。
- 模块本身成熟（97→117 测试、专家评审缺陷全部修复并有回归测试记录），是"等接入"而非"待完善"。

**接入价值：9/10**（全项目最高）

**接入清单**：
| # | 接入项 | 模块 | 形态 | 预期效果 |
|---|---|---|---|---|
| S-1 | **几何生成工具**：用地/建筑/道路真实生成（无间隙无重叠） | `generation.py` | subagent 工具 `generate_geometry`（或 run_python 白名单导入） | P0 几何真实化：替换 4 竖条带/3 矩形/1 直线/1 建筑 |
| S-2 | **专业图纸工具**：300dpi、指北针/比例尺/图例/来源标注 | `visualization.py` | subagent 工具 `render_figure` | P0 图纸真实化：替换 PIL 五胞胎；直接治 8/11 的图纸 2/10 |
| S-3 | **技术审查 AND 门**：solar/sponge/living_circle/setback fail-closed，view corridor/three-lines NOT_ASSESSED | `pipeline.py` | Gate 1 新增 C-TECH-* 系列（wrapper 调 TechnicalReviewRunner）+ `tech_review.json` 入提交包 | P1 技术分析：日照（GB 50180 大寒日≥2h）、海绵（≥85%）、生活圈、退线、视廊、交通承载力逐项可复算 |
| S-4 | 拓扑/投影复用 | `topology.py`/`projection.py` | 与 engine 现有 C-GEO 检查去重，单源化 | 消除"两套检查对同一批文件要求相反"的历史病灶（8/9 §7.3） |
| S-5 | 指标证据链图自动化 | `visualization.py` 4-panel dashboard | subagent 工具 | 治 8/11 "指标-正文-图层三方不一致" |

**两个子项目的评分汇总**：

| 项目 | 当前利用度 | 接入价值 | 一句话 |
|---|---|---|---|
| urban-design-knowledge | 5/10 | 8/10 | 状态机已接线但深度未用，剩余 3/4 领域价值在"技术分析与判词一致性" |
| urban-spatial-tooling | 2/10 | 9/10 | 117 测试的成熟工具库零集成；generation/visualization 是 P0 占位问题的现成解药 |

---

## 五、三阶段路线图

### 阶段一：契约闭环（M1-M2，短期）

**目标**：让"循环 DONE" ≡ "可提交"。先修 harness 侧五个 P0，再接入 S-1/S-2。

| # | 工作项 | 对应缺口 |
|---|---|---|
| 1 | Master 收尾：Gate 2 PASS 后执行 manifest 重生成 + self_check 强制重跑 + finalize 校验 | G-2 |
| 2 | ratchet 接线：每次 spawn 前快照、停滞/回退时恢复（已实现 60 行，只差调用） | G-1 |
| 3 | 统一验收函数：CODE + maintainer_review + Panel 合并为一个 `acceptance()` 作为循环唯一 Criteria | G-3 |
| 4 | Gate 2 默认启用 Panel（保留 heuristic 作为 pre-filter 省 token） | G-7 |
| 5 | run_python 沙箱堵 subprocess/os.system/ctypes | G-8 |
| 6 | spatial-tooling generation.py + visualization.py 接入为 subagent 工具 | S-1/S-2 |

**验收标准**：
- 循环一次 DONE 后 `maintainer_review.py` 实测 PASS（哈希全对、无占位 PDF、白名单文件名），self_check 与实测一致；
- 崩溃/停滞后 ratchet 恢复到最近最优快照，测试用例覆盖"回退拦截"；
- 对 test/test 包重跑，geometry 无整跨矩形、无越界，图纸通过视觉审委与指纹启发式；
- 全仓 pytest 通过（当前 241 测试）。

### 阶段二：领域深度（M3-M4，中期）

**目标**：把知识层与工具层的确定性检查全部收编进 Gate 1，让"零技术分析"判词失效。

| # | 工作项 | 对应缺口 |
|---|---|---|
| 1 | `pipeline.py` TechnicalReviewRunner 接线为 C-TECH-* 系列（solar/sponge/living_circle/setback fail-closed；view corridor/three-lines 数据门控 NOT_ASSESSED），`tech_review.json` 入包并进 compliance_matrix | G-5、S-3 |
| 2 | 状态机深度接线：C-SM-LANDUSE 升级用 judge_land_use；新增 C-SM-ZONES；三线几何校验数据门控 | G-4、K-1/2/3 |
| 3 | 控规指标几何复算：FAR/建筑密度/退线从 geometry 实测（治"声明 complete 但无内容"） | G-6、K-6 |
| 4 | 三层门禁验收函数扩展到 maintainer_review 的图纸页数与白占比检查进 Gate 2 启发式 | G-6 |

**验收标准**：
- Gate 1 新增 ≥10 条 C-TECH-*，每条有对应测试（沿用 spatial-tooling 的 fail-closed/NOT_ASSESSED 测试范式）；
- 对 test/test 包：solar/sponge/living-circle 至少一项有可复算实测值入 metrics.json；
- 68 测试状态机的判词逻辑（非仅成员检查）在 engine 中真实执行（代码覆盖率或调用计数证明）；
- tech_review.json 通过 schema 校验并进 manifest。

### 阶段三：概念创意层（M5+，长期）

**目标**：填补三层中的空缺层，并把系统泛化为"任意场地可复用"。

| # | 工作项 |
|---|---|
| 1 | **概念创意层建设**：品牌命名/文化叙事/场景卡全格式生成（含服务对象/数据来源/隐私边界/人工复核/运营主体五要素）——8/9 对比已证明"叙事厚度"是 prompt 与模板问题，不是模型能力问题；当前模板的"方案应…"祈使句骨架要重写为"本方案已…"交付句式 |
| 2 | 概念空间化自动映射："一带三核"等命名概念 → 真实几何（绿道线位/核点平面/半径图层） |
| 3 | 方案包达到正式评审门槛：≥7/10（专业评审维度全部有实物交付） |
| 4 | 参数化泛化：把 site 从代码常量变为数据（换场地 = 换 brief + boundary，不改 harness） |
| 5 | 公共知识沉淀：知识层笔记与工具层模块按 charter.8 沉淀回公共库 |

**验收标准**：
- 新场地（非京张）参数化运行，无需改 harness 代码即可产出包并通过 CODE + maintainer 门禁；
- 产出包通过模拟正式专业评审 ≥7/10（可复用 8/7 的规委视角评审方法）；
- 概念创意层的生成质量可量化对比（场景卡要素完整率、概念-几何落图率、叙事文本无"方案应"句式）。

---

## 六、最大风险点

1. **契约错位系统性复发（最高风险）**：8/9 已暴露三个不同错位（面积键回退、entries/requirements 键、图层命名自相矛盾），每次换模型都会重撞。根因是 schema、检查器、maintainer 门禁三处独立演化且无单一权威。**必须**在 M1 先做"三套门禁合并为单一验收函数"，否则阶段二、三都会在同一堵墙上反复撞。
2. **循环 DONE ≠ 可提交**：manifest 不收尾是系统性的，会让系统稳定地产出"自检全绿但收件即退"的包。这是当前 4/10 的直接机制原因。
3. **声明-交付断裂的占位模式**：LLM 会系统性地在矩阵里标 complete 而不交付实物（8/11 深度矩阵 15 项、10 个空壳 JSON 已两次出现）。对策是确定性内容门（几何实测、图纸指纹、指标复算），不可依赖 LLM 自检。
4. **本地模型能力上限**：30B 级模型的叙事厚度与判别力均不足（DeepSeek 版在品牌/案例上胜出是模板与 prompt 问题，但审委用同级模型评审同样受限）。Panel 的判词只能当"疑点清单"而非"终审"。
5. **数据门控的诱惑**：三区三线/视廊等官方 GIS 缺失时，最容易的"修复"是静默通过或宽松豁免（现有 C-SM-THREELINES 已带"国土空间"宽松豁免）。必须沿用 spatial-tooling 的 NOT_ASSESSED 语义：如实上报、不阻塞、绝不静默认证。
6. **沙箱逃逸**：subprocess 向量未堵。本机模型未利用是运气（8/9 DeepSeek 版已证明作弊动机存在）。无网络只能缓解、不能消除文件系统破坏。
7. **项目延期风险**：从 8/7 起每次评审都在推迟"真实达标点"（原估 R3，现 8/11 仍未达）。若征集截止前只做 P0 不做领域深度，产出物会停在"包装合规 + 内容单薄"。

---

## 七、最终判断

- **haidian 本体**：一套工程态度认真的自治系统，架构合理、稳定性工程化、可扩展性优良（6.5/10）；卡点不在"跑不动"，而在**验收标准测的是契约合规而非设计实质**，以及**循环的完成态从未等于提交态**（ratchet 死代码 + Master 不 finalize + 三套门禁分裂）。
- **两个子项目**：知识层已半接入（5/10 利用度），工具层零接入（2/10 利用度）——而它们恰恰握有 8/11 评审 P0/P1 的现成解药（真实几何生成、专业图纸、技术分析 AND 门）。
- **最短路径**：M1 修完契约闭环五件事（估 1-2 轮迭代），M2 接入 S-1/S-2 让 test/test 包越过 maintainer 门禁；M3-M4 技术分析入 Gate 1 让专业评审判词改写；M5+ 建概念创意层并泛化场地。最大风险不是技术，是**契约错位复发**与**声明-交付断裂**这两个已在三次评审中反复出现的系统性模式。

## 八、参考文件（绝对路径）

- 循环：`/Users/lijia/Projects/haidian/scripts/goal_driven_loop.py`、`/Users/lijia/Projects/haidian/scripts/run_autonomous.sh`
- 验证器：`/Users/lijia/Projects/haidian/constraints/engine.py`、`/Users/lijia/Projects/haidian/constraints/registry.json`、`/Users/lijia/Projects/haidian/constraints/state_machine_checks.py`、`/Users/lijia/Projects/haidian/constraints/state_machines/`（4 模块）
- 评审团：`/Users/lijia/Projects/haidian/scripts/panel_runner.py`、`/Users/lijia/Projects/haidian/review-panel/`（statutes/procedure/judge-prompts）
- 评审记录：`/Users/lijia/Projects/haidian/docs/final-submission-review.md`（8/11，4/10）、`/Users/lijia/Projects/haidian/docs/local-model-evaluation.md`（8/9）、`/Users/lijia/Projects/haidian/docs/professional-evaluation-2026-08-07.md`（8/7，5/10）
- 子项目：`/Users/lijia/Projects/urban-design-knowledge/`（7 笔记 + 4 模块 + 68 测试）、`/Users/lijia/Projects/urban-spatial-tooling/`（21 notebook + 17 模块 + 117 测试，`src/pipeline.py` 为对接点）
