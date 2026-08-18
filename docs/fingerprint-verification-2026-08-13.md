# haidian 提交物指纹核验报告（2026-08-13）

> 方法：grok-build 式"指纹"思路——每个声明/要求对应可验证的交付物，交付物以内容指纹（sha256）与机器检查结果佐证，声明-交付断裂由此暴露并修复。
> 对象：`submissions/test/test/`（专家评审二轮后，必须修+建议修全部落地）

## 一、四道闸门结果

| 闸门 | 结果 | 证据 |
|---|---|---|
| `ConstraintEngine.validate()` | **39/39 PASS** | 0 FAIL（修复 C-LAYER-002 / C-ASSUMPTIONS-001 / C-BOUNDARY-PROV×3 / C-TEXT-BOUNDARY-001） |
| `validate_submission.py` | **PASS** | 仅剩 known_blockers / provisional boundary 两条预期 warning |
| `self_check_submission.py` | **PASS / formal-review-ready** | Can enter formal review: YES |
| `pytest tests/` | **251 passed** | 含包一致性断言 6 用例 + 写盘白名单 4 用例 |

## 二、修复项指纹对照（要求 → 交付物 → 指纹 → 验证）

| 修复项 | 交付物 | 指纹 sha256:10 | 验证 |
|---|---|---|---|
| M-1 constraints 锁定图层 | `geometry/constraints.geojson` | `28169c0319` | C-LAYER-002 PASS |
| M-2 三区三线说明 | `proposal.md` | `4695365fd8` | C-TEXT-BOUNDARY-001 PASS |
| M-3 复算声明诚实化 | `metrics.json` / `self_check.json` | `77fc49f37c` / `bcc3f61d83` | METRIC_VERIFIABILITY PASS |
| M-4 design_depth 诚实注记 | `design_depth_matrix.json` | `248c42b9a4` | formal status=complete + status_note |
| M-5 agent 交付物入包 | `visual/assets/deliverables/`（27 文件） | 26 项 manifest 登记 | manifest 一致 |
| 引擎 C-ASSUMPTIONS-001 | `assumptions.json` | `2c5202b98b` | engine PASS（恢复 entries 契约） |
| 引擎 C-BOUNDARY-PROV×3 | `geometry/constraints.geojson` | `28169c0319` | boundary_precision 补齐 |
| 建议: sources 笔误 | `sources.json` | `cbb0e41524` | key_area→key_areas |
| 建议: copyright 补全 | `report/copyright_statement.md` | `be18bf5f7f` | license/授权/不侵权声明 |
| 建议: 重点区七要素 | `proposal.md` | `4695365fd8` | 三重点区各 7 要素小节 |
| 建议: 绩效指标 | `metrics.json` | `77fc49f37c` | 4 个 unknown 绩效指标 |
| 建议: 图纸图面 | `drawings/a0-boards.pdf` | `9cd56e4a8d` | 矢量平面/指北针/比例尺 |
| 建议: visual 措辞 | `visual/index.html` | `2b749fae85` | 示意网络措辞 |
| 建议: compliance 口径 | `compliance_matrix.json` | `f5647a6085` | self_check_ids 替换 16 处 unknown 引用 |

## 三、交付物指纹统计

- manifest 共 57 个条目；其中 manifest.json 自身无哈希，**其余 56 个文件 sha256 与磁盘 100% 一致**
- `visual/assets/deliverables/`：27 个交付物 JSON（11 个真实数据 + 15 个空壳补内容 + visual_index_section），全部入包登记
- 空壳清零：`submissions/test/` 父目录 15 个 `{"status":"complete","content":"<标题>"}` 空壳全部补为真实结构化内容

## 四、本轮新增/变更文件

- 新增：`scripts/generate_drawings.py`（图纸生成，含矢量平面图）、`tests/test_submission_package_consistency.py`（6 用例）、`tests/test_deepseek_design_write.py`（4 用例）
- 提交物变更：proposal.md（三区三线+重点区七要素）、constraints.geojson（图层名+boundary_precision）、assumptions.json（恢复 entries 契约）、design_depth_matrix.json（status_note）、metrics.json（绩效指标+复算边界）、sources.json（笔误）、self_check.json（声明诚实化）、report/narrative.md、report/copyright_statement.md、visual/index.html、compliance_matrix.json、drawings/*.pdf（矢量图面）、visual/assets/deliverables/（26 文件入包）

## 五、诚实声明（未解决/本质限制）

- **几何仍为 provisional 占位**（bbox 矩形/直线）：指纹核验证明"结构/声明/引用"一致，但**不改变设计实质**——空间设计的真实化是内容创作，不在指纹工程范围内
- `coordinated_research_area_sqm` 来源为组织方包外数据：已如实标注，非包内可复算
- 图纸为数据驱动概念表达（含矢量示意平面），非专业 CAD 设计图纸
- C-7 的"assumptions 去重"被引擎契约（读取 entries）推翻：恢复 entries 数组，双数组保留（引擎权威）

## 六、结论

**从产出看**：提交物已通过全部机器闸门（引擎 39/39、validate PASS、self_check formal-review-ready、251 tests），声明-交付一致（56/56 指纹匹配），空壳清零、交付物入包。**从设计实质看**：仍为 provisional 几何 + 概念表达，可进入正式评审讨论，但专业打分前必须完成几何真实化（官方 polygon 或专业设计）。
