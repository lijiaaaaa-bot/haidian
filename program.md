# haidian autoresearch

城市设计方案自动迭代。**评价器 = 统一 acceptance 失败数**（CODE + 内容下界 + self_check），越低越好。

## 评价器（canonical）

```bash
cd /path/to/haidian && python3 scripts/acceptance.py --submission submissions/test/autoresearch
```

输出示例：

```
FAILURES 42
# breakdown: code=4 content=6 self_check=32 | proposal=35675B h2=13 anchors=45 land_use=13
FAIL C-GEO-002 | land_use 未完全覆盖 site_boundary: ...
FAIL CONTENT-proposal-h2 | ...
FAIL SELF-CHECK-PROFESSIONAL-METRIC_PROPOSAL_REF | ...
```

目标是 **FAILURES 0**。仅 CODE 约束（旧行为）：

```bash
python3 scripts/acceptance.py --submission submissions/test/autoresearch --code-only
```

## 你只能改这些文件

- `submissions/test/autoresearch/proposal.md`
- `submissions/test/autoresearch/metrics.json`
- `submissions/test/autoresearch/compliance_matrix.json`
- `submissions/test/autoresearch/geometry/*.geojson`
- `submissions/test/autoresearch/assets/figures/*.png`（如需修图纸）

## 你不能改

- `constraints/`、`scripts/`、`brief/`、`schema/`、`templates/`、`data/`
- `manifest.json`（由 finalize 脚本刷新）
- 任何不在 `submissions/test/autoresearch/` 下的文件

## 实验循环

每轮做一件事：

1. 看 `git log` 了解之前试了什么
2. 跑 `python3 scripts/acceptance.py --submission submissions/test/autoresearch`
3. 从输出里**只挑一个** FAIL 项修
4. 改文件 → `git add` → `git commit -m "fix: <约束ID> <描述>"`
5. 再跑 acceptance
6. 失败数减少且内容未塌缩 → keep
7. 失败数不变/增加，或 proposal 章节/锚点明显变少 → `git reset HEAD~1 --hard`（放弃）
8. 记录到 `results.tsv`
9. 重复

## 向量棘轮（自动循环时）

`goal_driven_loop.py` / Cloud Agent 使用向量棘轮：失败数下降但 proposal 字节数跌超 20%、H2 章节变少、证据锚点变少时，改动会被回滚。

## 完成条件

`FAILURES 0` → 停止。

## NEVER STOP

一旦开始就不要停下来问"要不要继续"。改到失败数=0为止。

## 推荐入口

| 场景 | 入口 |
|---|---|
| 本地/Cursor 轻量循环 | 本文件 + `scripts/acceptance.py` |
| 本地 MLX 重型循环 | `bash scripts/run_autonomous.sh`（内部已接 acceptance） |
| 仅 CODE 快检 | `python3 scripts/goal_verifier.py --code-only` |
