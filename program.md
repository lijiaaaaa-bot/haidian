# haidian autoresearch

城市设计方案自动迭代。评价器 = 约束引擎失败数，越低越好。

## 评价器

```
cd /Users/lijia/Projects/haidian && python3 scripts/goal_driven_loop.py --submission submissions/test/autoresearch --dry-run 2>&1 | grep "^dry-run:" | grep -oP '\d+'
```

输出一个数字 = 当前失败数。目标是 0。

## 你只能改这些文件

- `submissions/test/autoresearch/proposal.md`
- `submissions/test/autoresearch/metrics.json`
- `submissions/test/autoresearch/compliance_matrix.json`
- `submissions/test/autoresearch/geometry/*.geojson`

## 你不能改

- `constraints/`、`scripts/`、`brief/`、`schema/`、`templates/`、`data/`
- `manifest.json`
- 任何不在 submissions/test/autoresearch/ 下的文件

## 实验循环

每轮做一件事：

1. 看 git log 了解之前试了什么
2. 看评价器输出，找到当前失败项
3. 决定改哪一个失败项 — 只改一个
4. 改文件 → git add → git commit -m "fix: <约束ID> <描述>"
5. 跑评价器
6. 失败数减少 → 留着 (keep)
7. 失败数不变或增加 → git reset HEAD~1 --hard（放弃）
8. 记录到 results.tsv
9. 重复

## 完成条件

评价器输出 0 → 停止。

## NEVER STOP

一旦开始就不要停下来问"要不要继续"。改到失败数=0为止。
