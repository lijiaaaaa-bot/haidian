# haidian 项目最终综合评审报告

**评审人**：专家组（专家组组长综合）
**日期**：2026-08-11（工作树状态：`main` @ 7fb4c21 + 未提交改动 scripts/goal_driven_loop.py / scripts/panel_runner.py / scripts/run_autonomous.sh）
**范围**：haidian 本体（Goal-Driven 循环 + 49 条注册约束 + 7 审委 Panel + 双模型/MLX subagent）及交付就绪度
**方法**：只读审查。逐文件读取 `scripts/goal_driven_loop.py`（2306 行）、`scripts/panel_runner.py`（482 行）、`scripts/run_autonomous.sh`、`scripts/mlx_client.py`、`scripts/scaffold_ai_submission.py`、`constraints/engine.py`、`constraints/registry.json`、`constraints/state_machine_checks.py`、`constraints/state_machines/`、`review-panel/`（statutes/procedure/judge-prompts）、`docs/goal-driven-entry.md`、`docs/comprehensive-review.md`（8/11 六维评审）、`docs/final-submission-review.md`（8/11，4/10）、`docs/m1-run-analysis.md`（8/9）；实测 `pytest`（232 通过 / 9 失败 / 96 subtests）、三处 `goal_driven_loop.py --dry-run`、`.goal-driven/` 状态与快照、各提交包文件实况。除本报告外未修改任何文件。

---

## 〇、结论摘要

| 项 | 结论 |
|---|---|
| 契约闭环三件套 | **已闭合**。ratchet 已接线（G-1 修复）、Master 已 finalize（G-2 修复）、快照与 best_failures 均已持久化（`.goal-driven/loop-state.json` = 2）。上次评审判为"死代码/缺口"的三处，本轮全部落地并有磁盘证据 |
| 图纸管线 | **专业图纸工具已接入**（generate_figure：EPSG:4548、300dpi、标题/图例/比例尺/指北针/来源标注，优先走 urban-spatial-tooling 渲染）。但末次运行的 5 张新图落入**错误目录**（`submissions/test/assets/figures/` 松目录），目标包 `submissions/test/test` 仍是 09:52 的 68–78KB 占位图 |
| 测试 | **9 项回归**（241 项中）：唯一根因 = scaffold 仍写 `land_use_code "05"`（`scaffold_ai_submission.py:203`），而枚举文件已按国标改为 09（3d76f86）。上次评审"契约错位复发"预警应验 |
| 循环运行实况 | `submissions/test/test` 当前 Gate 1 = **2 失败**（C-SM-BUILDING-HEIGHT、C-SM-ROAD-NETWORK），best_failures=2，未达 0，DONE 从未发生 |
| 综合判断 | 系统侧（架构/稳定性/可扩展性）**7–8 分区间**，交付侧（测试/产出物/提交就绪）**4.5–5 分区间**。harness 距"循环 DONE ≡ 可提交"只剩一层（统一验收函数 + 沙箱堵漏），产出物距 4/10 以上仍需 1–2 轮真实迭代 |

---

## 一、七维综合评分表

| # | 维度 | 得分 | 一句话结论 |
|---|------|------|-----------|
| a | 架构设计 | **8/10** | ratchet + Master finalize 已接线且有持久化证据；generate_figure 工具、MLX 迁移到位；残留：循环 Criteria ≠ maintainer 门禁、`max_turns` NameError、图纸输出目录未锁 |
| b | 约束覆盖 | **6.5/10** | 39 条 CODE 全启用 + 6 条 C-SM 状态机检查扎实（绿地率几何实测等）；但 judge_land_use 导入未用、three_zones 零接线、零 C-TECH 技术分析检查、05/09 枚举-生成器错位复发 |
| c | 质量评审 | **6.5/10** | Panel 工程大幅升级（DeepSeek 后端、逐文件证据预算、几何结构化摘要、fail-closed）；仍默认不启用；MLX 模式下面板易误配；启发式仍是指纹式可绕过 |
| d | 稳定性 | **8/10** | 八重恢复 + ratchet + finalize 幂等 + MLX 进程内加载（无 HTTP 服务崩溃面）；残留：subprocess 沙箱逃逸未堵、40 轮触顶崩溃（max_turns）、会话无检查点 |
| e | 可扩展性与集成 | **7/10** | 注册表驱动依旧；UST 可视化集成已验证（Way A 优先 + matplotlib fallback）；但技术分析 AND 门（S-3）、几何生成工具（S-1）未接；10 条 C-CHARTER 为惰性条目 |
| f | 测试与验证 | **5/10** | 241 项测试、CI 确定性校验在；但 9 项失败（单根因）、2306 行主循环与 482 行 Panel **零单测**、新 finalize/ratchet 路径无测试覆盖 |
| g | 整体成熟度与交付就绪 | **4.5/10** | 包内图纸仍占位（68–78KB）、A3/A0 仍为 118 字节 0 页 PDF、深度矩阵 15/15 全标 complete、54 个散落 JSON 未入包、muse-glimmer 包不完整；循环 DONE 未达、maintainer 门禁未测过 |
| | **平均综合** | **~6.5/10** | 一套认真工程化的自治系统，harness 已越过"契约闭环"门槛，卡点在"声明-交付断裂"与"产出物真实化"两个老病灶 |

---

## 二、逐维度评价与证据

### a) 架构设计 — 8/10（上次 7/10）

**本轮落实（有磁盘证据）**：
- **G-1 ratchet 已接线**：`main()` 每轮调用 `_ratchet()`（`goal_driven_loop.py:2215`），提升时 `_save_snapshot`、回退时 `_restore_snapshot`；best_failures 持久化 `.goal-driven/loop-state.json`（实测内容 `{"best_failures": 2}`），崩溃重启后基线不丢。`.goal-driven/snapshots/submissions-test-test/` 目录存在且内容完整（含 manifest/geometry/matrices）。
- **G-2 Master 已 finalize**：每次 Gate 1 PASS 后与 DONE 前均调用 `finalize_submission()`（`:2224`/`:2230`）；幂等（`_manifest_fresh` 先查哈希与 `package_state=ready_for_review`），并处理 finalize_submission.py 一次性 materiality 门禁的二次收尾问题（`_refresh_manifest_direct` 直刷兜底）。8/11 评审的"10 处 manifest 哈希失配"机制根因已消除。
- **generate_figure 工具**（四工具变五工具）：专业图纸渲染管线，Way A = urban-spatial-tooling `visualization`（`_import_ust` 导入 gen/proj/viz），Way B = matplotlib fallback；画布按场地长宽比自适应（`_canvas_from_bounds`，专治 16:12 画布 85%+ 留白触发 Gate 2 纯色启发式）+ 白边裁剪（`_trim_figure_margins`）。
- **MLX 迁移**：`run_autonomous.sh` 默认 `HAIDIAN_MLX=true`、模型换 MLX 4bit 版、监督循环不再硬重启 Ollama；`mlx_client.py`（新增，171 行）为 `_ollama_chat` 的 drop-in 替代（`<<<TOOL_CALL>>>` 标记解析、模型常驻内存）。

**残留缺口**：
- **G-3 验收目标仍分裂（部分缓解）**：finalize 已覆盖 maintainer 门禁中最大的一块（manifest 哈希 + package_state），但循环 Criteria 仍是 `engine.validate()` + Gate 2，`maintainer_review.py` 的 PDF 页数、文件名白名单、作者一致性、visual/professional 复核不在循环内。统一验收函数未建。
- **F-2（新）NameError**：`goal_driven_loop.py:1732` `log(f"  subagent hit max {max_turns} turns")` 引用未定义变量 `max_turns`（应为 `MAX_TOOL_TURNS`）。subagent 触顶 40 轮时主循环崩溃 → 监督重启 → 会话丢失，恰好摧毁了触顶提示想保留的状态。
- **F-3（新）图纸输出目录未锁定**：末次运行 5 张新图（330–422KB，8/11 16:47-48）写入 `submissions/test/assets/figures/`（松目录），而目标包 `submissions/test/test/assets/figures/` 仍是 09:52 的占位图（68–78KB），ratchet 快照亦为占位图。`_figure_submission`/`_handle_write_file` 允许解析到 `submissions/` 下任意子目录（沿 geojson 路径向上找包目录），输出可被 subagent 指到包外。
- 小瑕疵：`:2301-2302` 连续两行 `last_failures = failures` 重复赋值。

### b) 约束覆盖 — 6.5/10（上次 7/10）

**现状（registry.json 实测）**：`total_constraints=49` = **39 CODE + 10 LLM**，全部 enabled；category：spatial 24 / compliance 22 / metric 3；severity：critical 20 / high 29。CODE 检查函数 25 个（engine `_register_builtins` 全注册）。状态机六条 C-SM-* 全部为真确定性检查：
- C-SM-LANDUSE 枚举成员校验（读 `brief/site-package/enums/land_use_codes.json`）；
- C-SM-GEOMETRY-VALID 环闭合按**原始坐标**判定（防 shapely 自动闭合）、面积>0、is_valid；
- C-SM-BUILDING-HEIGHT 高度字段 + 1–500m 区间；
- C-SM-ROAD-NETWORK ≥3 条线（拒绝单线脚手架）；
- C-SM-GREEN-RATIO **几何实测绿地率**（EPSG:4548 投影复算），不读声明值。
- C-AREA×6（EPSG:4548 引用 + 六个面积键）与 C-ASSUMPTIONS-001 为本轮新增（8/11 提交），补上了 metrics 契约层。

**缺口**：
- **G-4 状态机深度仍未用**：`state_machine_checks.py:17-25` 导入了 `LandUseOrchestrator`/`judge_land_use`/`ZoneJudgementContext`/`ThreeLinesBoundaries`/`Parcel`，但全文件**无一处调用**（grep 仅命中 import 行）。three_zones（生态/农业/城镇三区判词）在 registry 中**无任何条目**。C-SM-THREELINES 仍是关键词 grep + "国土空间"宽松豁免，非几何校验。
- **G-5 零技术分析检查**：日照/海绵/生活圈/退线/视廊/交通承载力在 registry 中一个都没有；spatial-tooling 的 `pipeline.py` TechnicalReviewRunner 仍未接入（S-3 未做）。
- **F-4（新）10 条 C-CHARTER 为惰性条目**：registry 声明 `check_function: llm_charter_check`（charter.1–10），但**全仓无该函数实现**（grep 仅命中 registry）；`engine.validate()` 只执行 CODE 型；Panel 的 7 条 statute 不含 charter。注册表计数 49 被 10 条永不执行的条目虚增。
- **F-1（新，P0）枚举-生成器错位复发**：`scaffold_ai_submission.py:203` 写 `"05"`（产业服务与商业服务用地），而 `land_use_codes.json` 已在 3d76f86 按国标修正为 09；0702 一侧同理需复核。这正是上次评审"契约错位系统性复发"预言的再现——枚举改了，生成器没改。

### c) 质量评审（Gate 2）— 6.5/10（上次 6/10）

**升级（panel_runner.py 未提交 diff + 当前态）**：
- **DeepSeek 云端后端**：`HAIDIAN_JUDGE_BACKEND=deepseek` 走 anthropic 兼容端点（模型 `deepseek-v4-pro`），且主循环在该模式下**自动启用 Panel**（`use_panel` 判定含 `"deepseek" in HAIDIAN_JUDGE_BACKEND`）。
- 证据工程：逐 statute 逐文件字符预算（EVIDENCE_PLAN 重写为 `(file, cap)` 元组）、几何证据改为**结构化摘要**（ring 数/点数/闭合性/坐标样本，不再灌原始坐标数组）、`_compact_json` 保结构压缩 + 同名表格去重、judge 7 增补 copyright_statement.md、超时 300→480s、num_ctx 16384→24576、markdown 摘录保留 ## 标题大纲。
- 聚合规则沿用 procedure.json（`n_refuted ≤ 2 且 0 blocking` → APPROVED），fail-closed（超时/解析失败 → default_to_reject）。

**残留**：
- **G-7 Panel 仍默认不启用**（`--panel`/env 才开）；两次正式评审均未跑过真 Panel。**MLX 模式下新误配风险**：subagent 走 mlx_lm，但 `panel_runner` 的本地路径始终 POST `http://127.0.0.1:11434` —— 若 `HAIDIAN_MLX=true + HAIDIAN_PANEL=true` 而 Ollama 未跑，7 个审委全超时 → fail-closed 全拒。
- 审委模型与产出模型同级（qwen3.6:35b / deepseek-v4-pro），判别力上限受模型约束。
- 启发式 stub 仍是指纹式：78,378 字节、1640×840 脚手架配色、纯色 >80%、整跨矩形、`max_turns` 以上 "方案应" 套话计数——换模板即可绕过（8/11 的 32 PASS 0 FAIL 包内容 4/10 就是证据）。
- `/tmp/.hdk` 密钥文件（`panel_runner.py:293`）：/tmp 世界可读，仅限本机使用，属可接受但应知晓的边界。

### d) 稳定性 — 8/10（上次 7/10）

**增强**：ratchet（回退拦截 + 快照）已生效；finalize 幂等化（重复收尾不炸）；MLX 模式消除 Ollama HTTP 服务崩溃面（进程内加载、常驻内存）；模型失败计数持久化 `.goal-driven/model-failures.json`（实测 `{"qwen3-coder:30b": 1}`），重启给新生机会；`run_autonomous.sh` 监督循环在 MLX 下退避重试。

**残留风险**：
- **G-8 subprocess 沙箱逃逸未堵**：run_python prologue 只包 open/remove/unlink/rename/replace/write_text/write_bytes；不包 `subprocess`/`os.system`/`ctypes`。`subprocess.run([sys.executable, "-c", "open(...)"])` 的**子进程不继承 prologue**，可绕过全部写限制。m1 分析（8/9）把"沙箱无写限制"列为最严重缺陷——本轮主向量已堵（write_file 禁 harness 目录 + manifest.json），但逃逸向量仍在；无网络缓解了外联危害，文件系统写入仍可破坏。
- **F-2 崩溃点**：40 轮触顶 NameError → 进程崩溃；会话消息只在内存，崩溃即丢（快照机制可作检查点，但未用于会话）。
- 30s run_python 超时对重计算不友好（CPU-only 生产路径下可接受）。

### e) 可扩展性与集成 — 7/10（上次 8/10）

- 注册表驱动不变（新检查 = registry 条目 + engine 注册一个纯函数），`extractors.py` 生成 + manual_overrides 双源。
- **本轮集成实证**：generate_figure 证明"外部工具库 → subagent 工具"的接入路径已跑通（UST 导入成功走 Way A，失败自动降级 Way B），S-2（专业图纸）实现大半。8/11 评审"P0 图纸真实化"的机制已就位。
- **未接**：S-1（generation.py 真实几何生成工具——subagent 仍靠 run_python 手写几何，正是 m1 里"4 竖条带"的温床）、S-3（TechnicalReviewRunner 技术分析 AND 门）、G-4（three_zones/judge_land_use 判词）。
- F-4 惰性 charter 条目、检查函数注册仍硬编码于 engine（小扣分）。

### f) 测试与验证 — 5/10

- **总量**：`pytest` = **232 passed + 9 failed + 96 subtests（共 241）**。CI（`.github/workflows/submission-validation.yml`）跑确定性校验。
- **F-1（P0）9 项失败单根因**：`tests/test_maintainer_review.py`（4 项）、`tests/test_formal_scorecard.py`（2 项）、`tests/test_agent_scaffold_and_self_check.py`（3 项）全部栽在同一句：`geometry/land_use.geojson: feature[2]: unknown land_use_code '05'`。测试 fixture 只写 geometry，枚举来自真实 `brief/site-package/enums/land_use_codes.json`（已无 05），而 scaffold 仍生成 05 → 生成→finalize→自检→maintainer 链路断裂。上次评审"全仓 pytest 通过（241 测试）"当前不成立。
- **F-6 主循环与 Panel 零单测**：tests/ 无任何文件引用 goal_driven_loop / panel_runner；2306 行主循环的 ratchet/finalize/sandbox/模型切换与 482 行 Panel 的聚合规则全部裸奔。新 finalize 逻辑（`_manifest_fresh`/`_refresh_manifest_direct`/materiality-only 判定）无回归测试。
- F-7 `requirements-review.txt` 仍只有 jsonschema/Pillow/pyproj/shapely——matplotlib/geopandas/anthropic/mlx-lm 均为 loop/panel 实际依赖却未登记。

### g) 整体成熟度与交付就绪 — 4.5/10

**循环运行实况（实测）**：
- `submissions/test/test`：Gate 1 = **2 失败**（C-SM-BUILDING-HEIGHT：1/1 建筑高度不合规；C-SM-ROAD-NETWORK：仅 1 条道路）。`best_failures=2` 与实测一致，ratchet 正常工作。DONE 未达，maintainer 门禁未重测。
- `submissions/test/autoresearch`：5 失败（含 C-ENUM-land_use_codes 的 05 同款）。松目录 `submissions/test`：15 失败（metrics 契约类为主）。
- **末次运行图纸落点异常（F-3）**：新专业图进了松目录，目标包图纸还是 09:52 的 68–78KB 占位图——上次评审"图纸 2/10"的实物状态在**目标包内未变**。

**提交包状态（submissions/test/test）**：
- 图纸：5 张 68–78KB（09:52 生成，仍为占位族）；A3/A0 仍为 **118 字节 0 页占位 PDF**；
- `design_depth_matrix.json`：**15/15 全部 status=complete**——"声明-交付断裂"在矩阵层原样保留；
- `submissions/test/` 根目录 54 个散落 JSON（含上次评审点名的 10 个 58–75 字节空壳：brand_ip_system、conversion_pathway 等）**仍未入包**；
- `submissions/muse-glimmer/` 包不完整：无 proposal.md / manifest.json / geometry / report / figures（8 个文件 + 2 个 PDF），为中断运行残留。

**正面**：finalize 链已能保证"循环 DONE 的包哈希必对、package_state=ready_for_review"；专业图纸管线可用；若下一步把图纸生成指向正确目录并补技术指标，4/10 的门槛（门禁 FAIL）将首先被图纸与哈希两关突破。

---

## 三、上次评审缺口（G-1..G-10）状态核验

| 编号 | 缺口 | 状态 | 证据 |
|---|---|---|---|
| G-1 | ratchet 死代码 | **已修复** | `_ratchet` 接线（:2215）；`.goal-driven/snapshots/submissions-test-test/` 存在；loop-state.json 持久化 |
| G-2 | Master 不 finalize | **已修复** | Gate 1 PASS 后（:2224）与 DONE 前（:2230）双 finalize，幂等 + 直刷兜底 |
| G-3 | 验收目标分裂 | **部分缓解** | finalize 覆盖哈希/package_state；maintainer_review.py 全套仍未入 Criteria |
| G-4 | 状态机深度未用 | **未修** | judge_land_use 等仅 import；three_zones 无 registry 条目；THREELINES 关键词级 |
| G-5 | 零技术分析检查 | **未修** | registry 无 C-TECH-*；spatial-tooling pipeline 未接 |
| G-6 | 声明-交付断裂无感知 | **未修（机制已备）** | generate_figure + finalize 提供实物化路径，但 15/15 complete 矩阵与 0 页 PDF 仍在 |
| G-7 | Panel 默认不启用 | **部分** | 工程升级 + deepseek 后端自动启用；本地 MLX 下仍默认关，且有误配风险 |
| G-8 | run_python subprocess 逃逸 | **未修** | prologue 不包 subprocess/os.system/ctypes |
| G-9 | 子项目零集成 | **部分** | generate_figure 接入 UST visualization（S-2）；generation/pipeline 未接 |
| G-10 | land_use 枚举缺陷 | **修复一半** | 枚举 05→09 已改（3d76f86），但 scaffold 生成器未同步 → 本轮 9 项测试回归（F-1） |

---

## 四、本轮新发现缺口清单

| 编号 | 缺口 | 证据 | 影响 | 优先级 |
|---|---|---|---|---|
| F-1 | scaffold 写 land_use_code "05" 与枚举（09）错位，9 项测试回归 | `scaffold_ai_submission.py:203`；`pytest` 9 failed 全为 "unknown land_use_code `05`" | 生成→自检→maintainer 链路全线 FAIL；"契约错位复发"应验 | **P0** |
| F-2 | `goal_driven_loop.py:1732` `max_turns` NameError | 变量未定义（应为 MAX_TOOL_TURNS） | subagent 40 轮触顶即崩溃，会话丢失 | P1 |
| F-3 | generate_figure 输出目录未锁定到目标包 | 新图落 `submissions/test/assets/figures/`（16:47-48，330–422KB），目标包 `test/test` 仍占位（09:52，68–78KB）；`_figure_submission`/`_handle_write_file` 接受 submissions/ 任意子目录 | 图纸真实化成果落空；包外写入是写白名单过宽的同源问题 | P1 |
| F-4 | 10 条 C-CHARTER 惰性条目（llm_charter_check 无实现） | registry.json:520-679；engine 只跑 CODE；panel 无 charter | 注册表计数虚增，charter 十条原则无任何闸门执行 | P1 |
| F-5 | 沙箱 subprocess 逃逸（同 G-8 未闭环） | prologue 无 subprocess/os.system/ctypes 包装 | 恶意代码可绕过写限制破坏文件系统 | P0 |
| F-6 | 主循环（2306 行）与 Panel（482 行）零单测 | tests/ 无引用 | ratchet/finalize/聚合规则回归无护栏 | P1 |
| F-7 | 依赖清单缺失 matplotlib/geopandas/anthropic/mlx-lm | requirements-review.txt 仅 4 项 | 新环境部署即缺依赖 | P2 |
| F-8 | 小瑕疵：`last_failures` 重复赋值；`/tmp/.hdk` 明文密钥 | :2301-2302；panel_runner.py:293 | 无功能影响；本机安全边界 | P2 |

---

## 五、最大风险点

1. **F-1 枚举-生成器错位（当前已实证）**：3d76f86 只改了枚举没改生成器，9 项测试立刻红。教训固定为流程：改 `brief/site-package/enums/` 必须同步改 `scaffold_ai_submission.py` 并全仓 pytest。这是 G-3 统一验收函数的又一次代价示例。
2. **G-6 声明-交付断裂**：15/15 complete、0 页 PDF、54 个散落 JSON——LLM 会在矩阵里标 complete 而不交付实物，对策只能是确定性内容门（图纸指纹、PDF 页数、指标复算），不可依赖自检。
3. **F-3 图纸落点漂移**：专业图纸管线已就绪，若落点不定，产出的图纸不算产出于包。建议 generate_figure 强制绑定 `--submission` 目标（拒绝其他包路径）。
4. **G-8 沙箱逃逸**：subprocess 向量未堵，属 P0 级安全债；本机模型未利用是运气。
5. **Panel 未经验证**：两次正式评审都没跑过 Panel；MLX + Ollama 误配会静默全拒（fail-closed 的另一面是误杀）。
6. **评审标准错配**：39 CODE 全绿 + 深度矩阵 15/15 complete 的包内容分 4/10——Gate 1 测的是契约，不是设计；在 C-TECH 技术分析入 Gate 1 之前，"产出好方案"仍主要靠 subagent 自身的领域能力。

---

## 六、最终判断

- **harness 侧**：契约闭环三件套（ratchet / Master finalize / 快照持久化）已落地并有磁盘证据，稳定性 8/10、架构 8/10。距"循环 DONE ≡ 可提交"只剩：统一验收函数（把 maintainer_review 全套并入 Criteria）、沙箱堵 subprocess、图纸输出锁目录、修 F-2/F-4。**估 1 轮迭代。**
- **产出侧**：专业图纸管线已可用（S-2 大半完成），但末次运行图纸落空、包内图纸/PDF/矩阵仍是 8/11 评审的 4/10 状态；`submissions/test/test` 卡在 2 失败未达 DONE。**估 1–2 轮真实迭代**（先让 ratchet 循环自己把包推到 0 + 正确落图 + finalize，再过 maintainer 门禁）。
- **领域深度**：G-4（judge_land_use/three_zones）、G-5（C-TECH）未动，专业评审"零技术分析"判词在约束层依旧成立，属 M3–M4 工作。
- **一句话**：系统侧已从"跑得动、检得严"进到"闭环了、会收尾"，这是 8/11 以来实质的、可验证的进步；交付侧仍停在"契约绿、实物缺"的 4/10 区间，且新爆出 9 项测试回归与图纸落点漂移两个 P0/P1。**综合 6.5/10**——比 8/11 综合评审（6.5）持平偏稳，但组成变了：架构/稳定性各 +1，测试与交付的欠账被 F-1/F-3 兑现。

## 七、参考文件（绝对路径）

- 循环：`/Users/lijia/Projects/haidian/scripts/goal_driven_loop.py`、`/Users/lijia/Projects/haidian/scripts/run_autonomous.sh`、`/Users/lijia/Projects/haidian/scripts/mlx_client.py`
- 验证器：`/Users/lijia/Projects/haidian/constraints/engine.py`、`/Users/lijia/Projects/haidian/constraints/registry.json`、`/Users/lijia/Projects/haidian/constraints/state_machine_checks.py`、`/Users/lijia/Projects/haidian/constraints/state_machines/`
- 评审团：`/Users/lijia/Projects/haidian/scripts/panel_runner.py`、`/Users/lijia/Projects/haidian/review-panel/`（statutes.json/procedure.json/judge-prompts/）
- 生成器/收尾：`/Users/lijia/Projects/haidian/scripts/scaffold_ai_submission.py`、`/Users/lijia/Projects/haidian/scripts/finalize_submission.py`、`/Users/lijia/Projects/haidian/scripts/maintainer_review.py`
- 测试：`/Users/lijia/Projects/haidian/tests/`（241 项，9 失败）；CI：`/Users/lijia/Projects/haidian/.github/workflows/submission-validation.yml`
- 评审记录：`/Users/lijia/Projects/haidian/docs/comprehensive-review.md`（8/11）、`/Users/lijia/Projects/haidian/docs/final-submission-review.md`（8/11，4/10）、`/Users/lijia/Projects/haidian/docs/m1-run-analysis.md`（8/9）、`/Users/lijia/Projects/haidian/docs/professional-evaluation-2026-08-07.md`（8/7，5/10）
- 设计文档：`/Users/lijia/Projects/haidian/docs/goal-driven-entry.md`（8/7）
- 运行态：`/Users/lijia/Projects/haidian/.goal-driven/`（loop-state.json / model-failures.json / snapshots/）
