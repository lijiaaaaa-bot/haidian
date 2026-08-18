# 缺失真实数据清单

这些数据没有从当前公开资料中取得，AI agent 不得自行编造。拿到后应进入 `brief/site-package/`，并记录来源、日期、许可和公开性审查结论。

## 2026-08-13 进展（已落地数据）

以下数据已取得并登记（来源登记见 `data/source_registry.json`），AI agent 可引用：

- **采信通告全文**（official）：《京张铁路遗址公园沿线（人工智能创新街区重点地区）街区控制性详细规划（草案）公示采信情况的通告》，确认控规名称（HD00-1601 等街区 2022—2035）、公示期（2024-12-19~2025-01-19）、5 条意见全部采纳。原文：`data/sources/caixin-tonggao-hd1601-20250208.html`，要点：`data/processed/caixin-tonggao-hd1601-notes.md`。
- **走廊内地块控规指标实测库**（official，部分闭环 GAP-CONTROL-001）：从海淀区土地招拍挂公告附件「多规合一审核意见函」提取，`data/processed/konggui_parcel_indicators.csv`（36 行）；走廊内 8 地块（五塔寺 HD00-2002-10、蓝景丽家 HD00-1603-01/03A、清河站北-安宁庄、学院路北端 A/B/C/J）含容积率、建筑高度、绿地率、用地规模、地上建筑规模；证据 PDF 在 `data/sources/land-transfer/`。注意：多规合一函不含建筑密度（非控制指标）；未出让地块无官方指标。
- **天地图 WFS 背景矢量**（background_reference）：六图层（道路/铁路/水系/境界）3,148 要素，`data/processed/tianditu_wfs_beijing.geojson`，EPSG:4326。
- **依申请公开申请包**（待提交）：`docs/info-disclosure-application-2026-08-13.md` 含完整申请文书与渠道核验（规自委海淀分局窗口海淀区徐庄路9号院1号楼121室、010-67412068；线上需实名登录）。申请人身份信息字段留待用户本人填写后提交。

仍缺口（维持 provisional 纪律）：控规图则/用地规划图原件（公示条目已下架，走依申请公开）、三层范围与三重点区 official polygon、京张公园红线、清华园车站旧址文保范围 GIS（仅有文字四至）、未出让地块指标。

## 2026-08-14 进展（全量采集波次，来源登记见 `data/source_registry.json`）

- **天地图·北京标准地图**（background_reference，配准底图）：海淀 1:12万 / 中心城区 1:9万（走廊单图最佳底图）/ 北京 1:50万，JPG+PDF，地图本体审图号**京S(2025)041号**（页脚 004 号仅为网站版权号）。`data/sources/tianditu-bzdt/`，接口 standardmap.do 匿名直链。
- **OSM 现状底数**（background_reference，部分缓解 GAP-BUILDING-001 / GAP-SERVICE-001）：建筑 4000（按面积 top，原始 13255）、公共设施 POI 1920（学校/医院/养老/文化/商业等）、铁路遗迹 609（含清华园车站旧址 abandoned:railway=station node 1364084981）、绿地 2097。`data/processed/osm_*_corridor.geojson`，ODbL 1.0 需署名。
- **走廊锚点地理编码**（background_reference）：9 锚点实测坐标，`data/processed/anchors_geocoded.geojson`；**与 provisional 边界比对发现 3 处偏移**（大钟寺 polygon 偏南约 1.8km、AI 原点社区偏东约 1km、五道口站不在其内 895m）——维护者修正 provisional 边界时参考。
- **招拍挂指标实测库 v2**（official，进一步闭环 GAP-CONTROL-001）：84 条公告全量，119 行（corridor=yes 23），新增六郎庄 HD00-1010-0002/0003/0004（corridor=no，几何论证）与成交信息列（transaction_price/winner/transaction_date）。`data/processed/konggui_parcel_indicators_v2.csv`。
- **文物底数**（official）：海淀区不可移动文物名录 328 处（`data/processed/hd_buke_wenwu_minglu_2023.csv`，含走廊相关 7 处）；清华园车站旧址市级第九批文保定级 + 第十一批保护范围/建控地带**文字四至**（`data/sources/heritage/` + `data/processed/heritage-control-notes.md`）；京张公园一/二期仅文字范围（16.8 公顷/2.4km；53.09万㎡/9km），公开渠道无 GIS 红线。
- **地图 API 评估**：`docs/map-api-assessment-2026-08-14.md`——无 key 可用（Nominatim/Overpass/天地图 WFS/标准地图）已实测；需 key（高德 POI 与区县边界、天地图地理编码、北京开放平台 3 个候选数据集）给出接入路线图，用户注册 key 后可继续。

## 必须补齐

- 三个空间层次的精确官方 polygon：统筹研究范围、总体设计范围、重点区域范围。
- 三个重点区域的精确 polygon：众智园 AI 自主创新加速区、北京 AI 原点社区、大钟寺 AI 产业聚集区。
- 正式坐标系统和测绘基准说明。
- 控制性详细规划条件：容积率、建筑高度、建筑密度、绿地率、退线、建筑控制线、道路红线。
- 现状地块/宗地边界、土地权属或权属状态说明。
- 现状建筑轮廓、高度、层数、用途、建成年代、保留/改造/拆除状态。
- 京张铁路遗址公园一期/二期精确范围和已实施设计边界。
- 清华园车站旧址等文保范围、建设控制地带和相关管控要求的 GIS 图层。
- 交通基础数据：道路红线、断面、轨道站点边界、公交站点、客流、慢行断点、停车供给。
- 市政和安全约束：管线、排水、电力、燃气、消防通道、防洪排涝、海绵城市指标。
- 公共服务设施底数：学校、医疗、养老、体育、文化、社区服务、商业服务。

## 已有临时替代边界

`brief/site-package/geometry/provisional_boundaries.geojson` 已提供三层范围和三处重点区的 provisional polygons：

- `PROV-RESEARCH-001`：统筹研究范围，按公告约 43.6 平方公里和文字四至推定。
- `PROV-SITE-001`：总体设计范围，按公告约 11.4 平方公里和文字四至推定。
- `PROV-KEY-SCOPE-001`：重点区域范围，由三处重点区 provisional polygon 汇总。
- `PROV-KEY-001/002/003`：众智园 AI 自主创新加速区、北京 AI 原点社区、大钟寺 AI 产业聚集区。

这些边界只可用于 AI 生成、可视化、intake 自检和设计讨论；不得作为 official redline、审批依据、精确面积依据或正式专业评分依据。

## 可由维护者继续公开采集

- OpenStreetMap 道路、轨道、水系、绿地、POI 基础图层。
- 北京市公共数据开放平台交通、公共设施和统计数据；若需要 API，需要平台 `userKey` 或人工下载。
- 官方统计公报、政策文件、新闻发布、项目公告。

## 用户或业务方更可能需要提供

- 非公开或半公开的正式红线、地块、控规、建设控制线。
- 设计任务书附件、答疑、补遗、正式图纸。
- 经公开性审查可入库的 CAD/GIS/PDF 底图。
- 可以合法再分发的航片、正射影像或三维模型。
