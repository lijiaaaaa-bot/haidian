# 数据缺口对 haidian 产出质量的影响评估（2026-08-13）

> 结论：缺口对产出质量是**分级影响**——卡住 formal 定级的只有官方 polygon 一项；其余限制内容深度或设计自由度，不影响概念/品牌/AI 场景/文化等评分权重最高的维度，也不影响任何机器闸门。
> 本文为交接文档：后续由他人接手继续推进缺口闭合，据本文与 `docs/konggui-data-acquisition-plan-2026-08-13.md` 执行。

## 一、缺口影响分级

### 1. 卡硬性门槛（唯一影响提交物定级）

| 缺口 | 后果（引自 missing_data_checklist.csv impact_if_missing） |
|---|---|
| GAP-BOUNDARY-001 三层范围 official polygon | "只能进入 intake；不能 formal_review_ready" |
| GAP-BOUNDARY-002 重点区 official KEY_AREA polygon | "重点区只能做临时详细设计表达" |

评审团结论一致：机器闸门（validate/self_check/manifest 全部 PASS）之外，内容层 formal 门槛在**官方 polygon 与真实设计几何**。拿不到官方 polygon，提交物停留在 intake-provisional 级——这是产出质量天花板。

### 2. 限制内容深度

| 缺口 | 后果 |
|---|---|
| GAP-CONTROL-001 控规条件 | "只能提出概念建议和待确认条件"，不能给出审定容积率/建筑高度 |
| GAP-ROAD-001 道路红线 | "道路和慢行只能做概念组织" |
| GAP-PARCEL-001 宗地权属 | "更新项目只能写概念分区和待核条件"，不得指定拆改留 |
| GAP-BUILDING-001 现状建筑 | "建筑策略只能作为概念指引" |
| GAP-MUNICIPAL-001 市政 | "市政策略只能做体系建议" |

直接影响任务书 1.5.2.2"城市更新总体框架（控规深度）"交付深度：能讲清结构与策略，不能给出法定量化结论。

### 3. 设计保守化（限制自由度，不阻塞）

| 缺口 | 后果 |
|---|---|
| GAP-HERITAGE-001 京张公园红线、清华园文保范围 | "文化与公共空间设计必须保持保守" |

## 二、不受影响的维度

- 评分权重最高的概念、品牌、AI 场景、文化叙事——不依赖官方几何（专业评审原话："比赛评分权重在概念、品牌、AI场景、文化，恰好是AI有优势的维度"）。
- 全部机器闸门：ConstraintEngine 39/39、validate PASS、self_check、manifest、251 项测试。
- 合规性：缺口如实标注 provisional、写入 assumptions.json，符合竞赛合规纪律。

## 三、2026-08-13 已收窄的缺口（本轮工作成果）

| 项 | 状态 |
|---|---|
| GAP-CONTROL-001 | **部分闭环**：走廊内 8 地块 official 指标（五塔寺/蓝景丽家/清河站北/学院路北端），来源=多规合一函（`data/sources/land-transfer/`），实测库 `data/processed/konggui_parcel_indicators.csv` |
| 控规公示信息 | 采信通告全文已归档（官方确认名称/公示期/5 条采纳意见），`data/sources/caixin-tonggao-hd1601-20250208.html` |
| 交通背景 | 天地图 WFS 六图层 3,148 要素（background_reference），`data/processed/tianditu_wfs_beijing.geojson` |
| 依申请公开 | 申请包就绪 `docs/info-disclosure-application-2026-08-13.md`，渠道实测；**待申请人填写身份信息后提交** |

## 四、遗留缺口与负责人建议（交接）

| 缺口 | 建议负责人 | 动作 |
|---|---|---|
| 三层范围/重点区 official polygon | 用户/业务方 | ①提交依申请公开（申请包已备）②核查资格预审文件附件/补遗答疑 ③关注规自委正式发布 |
| 控规图则/用地规划图原件 | 用户/业务方 | 依申请公开答复后取件；答复若仅给图件，再单独申请指标表电子数据 |
| 清华园文保范围 | 技术执行 | 文物局（wwj.beijing.gov.cn）渠道，未验证 |
| 未出让地块指标 | 技术执行（持续） | 新出让/规划许可公示增量登记（脚本 `scripts/extract_land_transfer_indicators.py` 可复用） |
| 道路红线/市政/宗地 | 用户/业务方 | 依申请公开；否则维持 provisional |

**优先级**：官方 polygon > 控规图则原件 > 文保范围 > 其余。官方 polygon 拿不到时的次优解：投入专业级自绘设计几何（真实地块轮廓+专业图纸），可显著改善空间品质分，但 formal 定级仍不可达。

## 五、来源登记状态

`data/source_registry.json` 现 11 条（新增：采信通告 DATA-SRC-CAIXIN-TONGGAO-HD1601-20250208、招拍挂指标库 DATA-SRC-LAND-TRANSFER-KONGGUI-INDICATORS-20260813），validate PASS；`source-registry-data.js` 已重新生成。
