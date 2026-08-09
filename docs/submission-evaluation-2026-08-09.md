# 提交包独立评价报告：submissions/test/test（京张智脉共生带 v0.3）

**评价人**：百年京张AI创新带开源征集项目总负责人（独立复核）
**日期**：2026-08-09
**评价对象**：`/Users/lijia/Projects/haidian/submissions/test/test/`（proposal.md + 8 个 JSON 元数据 + 12 个 geometry 文件 + 5 张 PNG + 2 个 PDF 图纸 + HTML 产物）
**方法**：只读审查；对全部几何图层做独立测地线面积复算；运行仓库自带门禁 `scripts/maintainer_review.py` 与 `scripts/self_check_submission.py`；对照任务书 `brief/site-package/agent_taskbook.json` 六项 agent 任务逐一核验。

---

## 一、评分总结表

| # | 维度 | 得分 | 一句话结论 |
|---|------|------|-----------|
| 1 | 任务覆盖度 | **5/10** | agent.1/2 有实质内容，agent.3/4 部分覆盖，agent.5 单薄，agent.6（运营机制）完全缺失；但矩阵与 self_check 宣称全部覆盖 |
| 2 | 空间数据质量 | **3/10** | 投影/拓扑/面积计算技术上正确，但全部图层是脚手架占位（4 条竖条带、3 个轴对齐矩形、1 个建筑矩形、空 constraints） |
| 3 | 指标可信度 | **4/10** | 面积类指标真实可复现（独立复算误差 <0.1%）；计数类指标编造（5 用户画像、4 地标在文中零出现） |
| 4 | 专业合规性 | **4/10** | provisional 声明与边界条款执行优秀；但三张矩阵是样板话术，引用了 proposal 中不存在的章节，manifest 22 处哈希失配 |
| 5 | 图纸质量 | **2/10** | 五张 PNG 是脚手架几何的 matplotlib 风格示意图（竖条带/矩形/柱状图）；a0/a3 两张"图纸"是 599 字节同名占位 PDF |
| 6 | 方案深度 | **4/10** | 文本是合格的"品牌咨询报告"，不是城市设计方案；无现状诊断、无拆改留结论、无分期、无运营机制 |
| 7 | 整体判断 | **不可提交** | 仓库门禁判定 request-changes、can_enter_formal_review=False；最大短板是"声明-内容"系统性断裂 |

**加权综合（按 review-rubric 权重近似）**：约 **3.8/10**。专业评审 5/10 的结论（方法论层面对标设计院）在本提交包上得到印证且更弱：方法论文档缺失的内容域，这里直接以"标记 complete 但未交付"的方式呈现。

---

## 二、逐维度评价与证据

### 1. 任务覆盖度 — 5/10

对照 `brief/site-package/agent_taskbook.json` 六项任务的 must_address 逐项核验 proposal.md：

| 任务 | 要求 | 实际交付 | 判定 |
|------|------|---------|------|
| agent.1 总体概念 | 命名体系/Logo方向/三大定位五大功能/三区两翼/空间结构图 | 命名体系、Logo 方向（人字形轨道→智能流线）、三大定位、五大功能、三区两翼回路——内容真实、成体系 | **覆盖** |
| agent.2 创新生态 | 5-8 案例/生态图谱/要素机制 | 8 个全球案例（列表式）、三维生态图谱（文字版）、8 项要素机制 | **基本覆盖**（无 case_study_table、无生态图谱图） |
| agent.3 AI+场景 | ≥10 场景卡/≥3 测试验证/≥5 用户画像/场景-空间-运营映射 | 10 个场景**一句式提及**（非场景卡格式）；3 个测试验证场景（自动驾驶、机器人、压力测试）；**用户画像 0 个**；映射矩阵无 | **部分覆盖，缺口大** |
| agent.4 公共空间/地标 | ≥3 朝圣地标/荣誉展示体系/组件库/东西缝合 | 公共空间与组件库有概念；**朝圣地标 0 个**（"朝圣"全文仅 1 次，在摘要里）；荣誉展示体系无 | **部分覆盖** |
| agent.5 文化叙事 | 京张文化资源系统/导视符号/国际传播叙事 | 仅有命名与材料转译（红砖/锈板/古钟）数句；导视/符号系统无 | **单薄** |
| agent.6 运营机制 | 年度活动体系/社区运营/场景开放运营/转化路径 | **完全缺失**："活动体系"全文 0 次，"运营"仅 3 次且均为虚指 | **缺失** |

反面证据（矩阵/自检的虚假覆盖）：
- `compliance_matrix.json` 中 21 条 requirement 与 21 条 entry 的 report_sections/geojson_layers/metrics/source_ids/assumption_ids/self_check_ids **逐项完全相同**，无逐条证据、无 pass/fail 判定，是复制粘贴的样板。
- `self_check.json` 声称 "ALL_SECTIONS_PRESENT: All 13 required sections present"、"5 user personas defined"、"4 AI pilgrimage landmarks"——与 proposal.md 实际内容矛盾（proposal 只有 6 个 H2 章节；用户画像/地标全文零出现）。
- `design_depth_matrix.json` 的 14 个深度项全部 status="complete"，其中包括 proposal 中不存在的内容（existing_conditions_diagnosis 现状诊断、phasing_implementation 分期、"分期"全文 0 次、renewal_project_list——proposal 明确写着"本方案不提供任何具体地块的拆改留结论"）。

### 2. 空间数据质量 — 3/10

**技术正确性（加分项，独立验证）**：
- 坐标系：WGS84 经纬度存储，面积按声明用 EPSG:4548/测地线计算。我用测地线公式独立复算：site_boundary 11,399,944 m² vs 声明 11,412,825（99.9%）；green_space 1,407,007 vs 1,408,601；public_space 835,400 vs 836,346；buildings 310,457 vs 310,807；phasing 783,250 vs 784,137；三处 key_areas 1.927/1.042/0.720 km² vs 声明 1.929/1.043/0.720——全部 0.1% 内一致。
- 拓扑：land_use 四块多边形**无缝隙无重叠地精确铺满**场地（总面积=场地面积）；引用的源文件 `brief/site-package/geometry/provisional_boundaries.geojson` 六个 PROV-* feature 真实存在。
- 面积指标的来源链（metrics.json source_files → 源 GeoJSON）真实可追溯。

**但是——这是脚手架，不是设计（决定性缺陷）**：
- `land_use.geojson`：4 个多边形是沿经度切分的**四条竖条带**（116.3441/116.3472/116.3512 三刀切），各占 23.4%/22.7%/29.5%/24.4%——比例与 proposal 表格数字完全一致，证实表格数值就是从这四条条带反推的，而非设计意图。
- `key_areas.geojson`：三处"重点片区"全部是**轴对齐矩形**（5 顶点 = 4 角 + 闭合），proposal 自己承认"Provisional polygon 为矩形粗略范围"。
- `buildings.geojson`：整个 11.4 km² 设计范围只有 **1 个矩形**建筑基底（310,807 m²）。
- `green_space.geojson` 1 个矩形（横跨 6 km 走廊）、`public_space.geojson` 1 个矩形、`roads.geojson` 1 条 LineString（绿道中线）、`constraints.geojson` **0 个要素（空文件）**——而 design_depth_matrix 引用它作为证据。
- 12 个 geometry 文件中有 **4 对内容完全相同的重复文件**（buildings==building_footprint、key_areas==key_area、roads==road_centerline、phasing==phase），后四个文件名不在仓库白名单内（门禁报错），说明是脚手架脚本两代输出的混合残留。
- site_boundary 是 9 顶点的粗略替代边界（longitude 跨度仅 0.0156°≈1.4km、latitude 跨度 9.7km 的窄带），已诚实标注 provisional_rough，但"控规深度城市设计"建立在这样的边界上只能是概念占位。

### 3. 指标可信度 — 4/10

**可复现（真实计算）**：site_area_sqm、overall_design_area_sqm、coordinated_research_area_sqm（43.56 vs 43.61 km²，0.1%）、key_detailed_design_area_sqm、三个分区面积、building_footprint/green/public 面积、green_ratio 0.123、public_space_ratio 0.073——公式写明、源文件指实、独立复算一致。FAR 2.5、高度 60m 诚实标注为 directional placeholder（confidence=low）。

**编造（不可复现）**：
- `user_persona_count: 5`，source_files 指向 proposal.md——proposal 中"用户画像/persona"**零出现**。
- `ai_landmark_count: 4`——proposal 中无任何地标描述。
- `renewal_project_count: 6`，source_files 指向 phasing.geojson——该文件只有 **1 个** feature。
- `dongxi_connection_count: 6`，source_files 指向 roads.geojson——该文件只有 **1 条** LineString。
- metrics.json 本身未通过仓库 schema 校验（"metrics must be a non-empty object"）。

即：**能算的都算了且算对了；不能算的直接编了数字**。

### 4. 专业合规性 — 4/10

**执行得好**：
- provisional 声明体系完整且贯彻全包：proposal 声明（第 32-34 行、66 行、283 行）、assumptions.json（A-CONTROLS-001 等 6 条 + 6 条概念假设，全部 pending_professional_confirmation/concept_proposal）、metrics 每项带 assumptions。
- 边界条款执行合规：全文"概念建议/待专业确认"措辞一致，无禁止性法定结论；门禁 mandatory_rejection_hits = 0（无禁用措辞）。
- `[clause:boundary_clause]`、`[charter:charter.6]`、`[standard:*]` 等锚点在 `constraints/registry.json` 中真实存在，引用有效。
- sources.json 7 条来源含类型与用途声明；官方公告 URL 为真实北京规自委链接。

**系统性失真（致命）**：
- compliance_matrix / standard_matrix / design_depth_matrix 三张矩阵共 41+6+14 条记录，引用字段全部是同一套样板；所有条目 review_status="addressed" 或 status="complete"，包括实际不存在的内容。
- 三张矩阵引用的 proposal 章节 `指标体系、面积复算与合规矩阵`、`风险、版权与合规说明` 在 proposal.md 中**根本不存在**（proposal 仅有 6 个 H2）。
- manifest.json 22 个文件哈希与实际不符（自检逐项报错），却声明 package_state="ready_for_review"、data_confidence="high"、known_blockers=[]。
- 缺失关键引用：`[standard:PROJECT-AGENT-OPEN-CALL-TASKBOOK]`（本次征集的核心标准）未引用；4 个 `[data:geometry/...]` 引用缺失；`[depth:metrics_recalculation]`、`[depth:phasing_implementation]`、`[depth:risk_missing_data]` 缺失。
- 目录里残留 `test_write.txt`（4 字节测试残留物）。

### 5. 图纸质量 — 2/10

- 五张 PNG（site-overview / land-use-structure / key-areas / mobility-bluegreen / metrics-evidence）经目视检查：是**脚手架几何的直接绘图**——竖色条带图、三个矩形标注图、绿色带+线条示意图、指标柱状图。无底图影像/路网背景、无指北针、无比例尺、无剖面/立面/体量图，不是城市设计图纸，也谈不上"随机色块"——它们是**忠实描绘占位几何的示意图**，这本身就是问题。
- `drawings/a0-boards.pdf` 与 `drawings/a3-booklet.pdf`：**完全相同的 599 字节占位 PDF**（文件哈希一致），内容仅一行文本 "JingZhang AI Belt Design"。两张"A0 展板/A3 图册"实质为空。
- manifest 中这两份 PDF 记录同一 sha256，进一步确认是同一占位文件复制改名。

### 6. 方案深度 — 4/10

- 与专业评审 `docs/professional-evaluation-2026-08-07.md`（5/10："品牌咨询报告 vs 城市设计方案"）结论一致，且本提交在内容广度上更弱：
- **策略层是真实内容**：命名体系、三大定位/五大功能、三区两翼协同回路、8 个国际案例、重点区功能描述——可读、成体系、有咨询报告水平。
- **设计层几乎空白**：无现状诊断（无建筑质量/权属/交通量/人口基线）、无地块/街区尺度设计、无拆改留结论（明确拒绝交付）、无交通组织与停车（"停车"0 次）、无市政策略（"市政"3 次均为虚指）、无分期实施（"分期"0 次）、无运营机制、无文化导视系统、无实施指标。
- design_depth_matrix 的 14 项"complete"与正文严重脱节——这是**用合规外壳包装内容空洞**，比内容缺失本身更伤可信度。

### 7. 整体判断 — 当前不可提交

**门禁实测**（`python3 scripts/maintainer_review.py submissions/test/test --pr-author test`）：
- recommendation = **request-changes**，can_enter_formal_review = **False**
- deterministic_validation = FAIL：8 个必需章节缺失（AI 创新生态人才画像与 AI+场景 / 用地建筑规模与拆改留 / 交通轨道市政 / 蓝绿公共空间风貌 / 更新清单实施分期 / 指标体系面积复算合规矩阵 / 风险版权合规说明 / 参考资料）；22 处 manifest 哈希失配；4 个非白名单几何文件名；test_write.txt 残留；metrics-evidence.png 未嵌入；5 项引用缺失
- visual_packaging = FAIL（VISUAL_METRIC_SOURCE_MISSING ×3）
- professional_review = FAIL（STANDARD/DEPTH/DATA_PROPOSAL_REF ×8）
- 仓库测试套件 `tests/test_agent_scaffold_and_self_check.py` 3 项失败（生成的脚手架夹具无法通过完整自检与内容评审门禁）

**结论：不能提交。** 即便忽略"几何是占位、图纸是空"的专业短板，单是自检/矩阵/清单/正文四者互相矛盾这一条，维护者门禁和任何认真评审都会在 10 分钟内拒绝。

**轮次建议（若继续自主迭代）**：
- **R1 — 包装完整性**（1 个迭代）：恢复 13 章节结构、重新生成 manifest 哈希、删除重复几何与 test_write.txt、嵌入全部 5 图、补齐 5 项引用、按真实结果重写 self_check 与三张矩阵 → 目标：通过 deterministic gate。
- **R2 — 内容补齐**（1-2 个迭代）：交付 agent.3 的 5 类用户画像与 10 张场景卡（卡格式+场景-空间-运营映射）、agent.4 的地标清单与荣誉展示体系、agent.6 的年度活动体系/社区运营/转化路径、文化导视系统；矩阵逐条给出真实证据，不再整条复读样板 → 目标：通过 professional evidence gate。
- **R3 — 空间设计真实化**（2-3 个迭代）：用真实设计的用地布局、地块/街区图层、交通网络、蓝绿系统替换竖条带与矩形占位；补 constraints 图层与多期 phasing；重绘带底图/指北针/比例尺的图纸 → 目标：可进入正式评审。
- **R4 — 专业深化**：现状诊断、控规图则化表达、三区三线校验、技术分析（日照/视廊/海绵）——这是专业评审 5/10 指出的方法论天花板，属于"够好之后能否胜出"的问题。

在当前"无 official polygon、无控规条件"的客观约束下，"够好"的合理定义是：**通过维护者门禁 + 自检与正文一致 + 无编造指标 + 图纸与几何为真实设计而非占位**。按现有 agent 自主迭代效率估算，达标点在 **R3 结束（约第 4-6 轮迭代）**；若官方 geometry 在 R3 前发布，需整体重算，轮次顺延。

**最大短板（一句话）**：不是"设计水平低"，而是**声明与交付的系统性断裂**——self_check 全绿、矩阵全 complete、manifest 声称 ready，而正文缺 8 个章节、缺 4 项任务内容、缺 22 处有效哈希。这个短板让任何专业内容上的努力都被归零，必须最先修复。

---

## 三、附：评价过程中的重要核实与更正

1. 初查时我用错误的面积公式得到"面积与声明差 58.8%"的结论；改用球面过剩公式独立复算后，全部面积指标与声明值一致（<0.1% 误差），确认**面积类指标为真实计算**，本报告以复算结果为准。
2. 五张 PNG 逐一目视检查；两张 PDF 用文件哈希与 strings 检查确认为同名占位文件。
3. 门禁与测试结论为本地实际运行结果（2026-08-09），非推断。

## 四、参考文件（绝对路径）

- 方案主文档：`/Users/lijia/Projects/haidian/submissions/test/test/proposal.md`
- 指标/假设/合规/深度矩阵：`/Users/lijia/Projects/haidian/submissions/test/test/{metrics,assumptions,compliance_matrix,standard_matrix,design_depth_matrix,self_check,manifest}.json`
- 空间数据：`/Users/lijia/Projects/haidian/submissions/test/test/geometry/*.geojson`
- 图纸：`/Users/lijia/Projects/haidian/submissions/test/test/assets/figures/*.png`、`drawings/*.pdf`
- 任务书：`/Users/lijia/Projects/haidian/brief/site-package/agent_taskbook.json`
- 门禁脚本：`/Users/lijia/Projects/haidian/scripts/{maintainer_review,self_check_submission,scaffold_ai_submission}.py`
- 专业评审参照：`/Users/lijia/Projects/haidian/docs/professional-evaluation-2026-08-07.md`
- 评审标准：`/Users/lijia/Projects/haidian/docs/review-rubric.md`
