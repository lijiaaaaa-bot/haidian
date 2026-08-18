# 地图 API 价值评估与接入方案（京张走廊 AI 创新带）

> 评估日期：2026-08-14 · 作者：数据工程（技术实测）× 合规审查
> 铁律：本文所有"实测"结论以 curl 输出为准（HTTP 状态码、返回内容均已记录）；未实测内容一律标注"未验证"；不替代 `data/source_registry.json` 登记（由维护者统一执行）。
> 关联文档：`docs/konggui-data-acquisition-plan-2026-08-13.md`、`docs/official-data-acquisition-brief.md`、`brief/site-package/missing-data.md`、`data/processed/tianditu_wfs_beijing-notes.md`。

---

## ① 结论摘要

**先用（0 成本、已实测打通）**：
1. **Nominatim 地理编码** — 走廊 9 个锚点全部拿到经纬度（`data/processed/anchors_geocoded.geojson`，EPSG:4326），用于核验 provisional 边界与文字四至的一致性，**已发现 3 处锚点与 provisional 多边形偏移**（见 §3），是当前最有价值的无 key 成果。
2. **天地图 WFS**（`gisserver.tianditu.gov.cn/TDTService/wfs`）— 已落地 3,148 要素背景矢量（道路/铁路/水系/境界），继续作为 georeference 与背景层。
3. **天地图 WMS**（`gisserver.tianditu.gov.cn/TDTService/ows`）— 实测无 key 可出图，但**仅 1 个图层（AANP 注记）**，价值有限。
4. **北京市公共数据开放平台** — 搜索/详情页匿名可看，**下载与 API 需注册 userKey**（无匿名下载）；3 个候选高价值数据集已记录（`data/sources/beijing-data-open/README.md`），待用户注册后下载。
5. **OpenStreetMap Overpass**（本轮附带验证）— 无 key 可取道路命名与节点（用于"学院路北端"等 Nominatim 无法精确解析的锚点）。

**后申请（免费 key，按优先级）**：
- **P0：高德开放平台**（行政区域查询→海淀区边界背景参考；POI 搜索→学校/医院/商超/充电站设施底数，直接缓解 **GAP-SERVICE-001**；地理编码→与 Nominatim 交叉验证）。
- **P0：天地图开放平台**（地理编码/逆地理编码、行政区划、POI 搜索→同上交叉验证；影像底图 img_c 瓦片→公开底图，竞赛图件 georeference 参考）。
- **P1：百度地图 / 腾讯位置服务**（高德备选与交叉验证；交通路况背景）。
- 商业地图 POI/边界数据一律按 `background_reference` 使用，**不替代 official 边界与控规指标**（GAP-BOUNDARY-001/002、GAP-CONTROL-001 的官方数据仍走依申请公开路径）。

**不碰**：涉密测绘成果（≤1:1万地形图、宗地权属、地籍、竣工图）；不申请商业授权场景（本项目为竞赛/研究用途）。

---

## ② 无 key 实测结果表（2026-08-14 curl）

| # | 服务 | 端点（实测） | 实测结果 | 结论 |
|---|---|---|---|---|
| 1 | Nominatim 地理编码 | `https://nominatim.openstreetmap.org/search?format=json&q=<关键词>&limit=1&countrycodes=cn` | HTTP 200；9 锚点逐点限速 1.2s 间隔 + User-Agent 注明用途；**7 个一次命中，2 个需细化**（清华园车站→改查"清华园车站旧址"命中站房博物馆；学院路北端→Nominatim 误匹配广东肇庆，改用 Overpass 取道路最北节点） | ✅ 可用。产出 `data/processed/anchors_geocoded.geojson`（9 features）。数据 © OpenStreetMap contributors，ODbL 1.0；须限速 ≤1 req/s、带说明用途的 User-Agent、成果署名 |
| 2 | 天地图 WFS | `gisserver.tianditu.gov.cn/TDTService/wfs?service=WFS&version=1.1.0&request=GetCapabilities` | HTTP 200（10 图层：AANP/AGNP/BOUA/BOUL/HYDA/HYDL/LRDL/LRRL/RESA/RESP）；GetFeature 取数已于 2026-08-13 落地 3,148 要素 | ✅ 可用（已有记录） |
| 3 | 天地图 WMS | `gisserver.tianditu.gov.cn/TDTService/wms?service=WMS&request=GetCapabilities`；GetMap 经 `gisserver.tianditu.gov.cn/TDTService/ows?SERVICE=WMS&...` | GetCapabilities HTTP 200（WMS 1.3.0，236KB）；**GetMap 无 key 实测返回 PNG（600×600）**；但 GetCapabilities 仅声明 **1 个图层 AANP（注记）** | ⚠️ 部分可用：无 key 可出图但只有注记层，不能当底图 |
| 4 | 天地图 WMTS 瓦片 | `tiles.tianditu.gov.cn/vec_w/wmts?...`（HTTPS）；`t0.tianditu.gov.cn/vec_w/wmts?...&tk=test`（HTTP） | HTTPS 握手失败（SSL_ERROR_SYSCALL）；HTTP 端点返回 **HTTP 418 CloudWAF 拦截页**（"您的请求疑似攻击行为！"） | ❌ 无 key 不可用。矢量/影像瓦片需开发者 key（tk），且需合规客户端 |
| 5 | 北京市公共数据开放平台 | 搜索 API `data.beijing.gov.cn/cms/web/search?columns=<关键词>`；详情页 `data.beijing.gov.cn/zyml/.../contentId.htm`；下载 `data.beijing.gov.cn/cms/data/downloadResource/<fileId>` | 搜索 API 匿名 HTTP 200（JSON，可查命中数）；详情页匿名 HTTP 200（开放条件均标"无条件开放"）；**下载端点匿名返回登录页**；API 参数含 `userKey`（登录后【用户中心】获取） | ❌ 无匿名下载。许可条款已完整记录（`data/sources/beijing-data-open/legal-notice-extract.md`）：免费+非排他使用+须注明来源"北京市公共数据开放平台"+应用备案+免责声明 |
| 6 | OSM Overpass（附带） | `overpass-api.de/api/interpreter`（POST 查询） | 可取道路 way 及节点（"学院路"命名道路最北节点 39.999701/116.346825；延续路"学清路"最北节点 40.022415/116.344781，近北五环上清桥）；首次请求偶发 HTML 错误页，重试即成功 | ✅ 可用（无 key）。ODbL 许可，需署名 |

---

## ③ 锚点核验结果（Nominatim × provisional 边界一致性）

`data/processed/anchors_geocoded.geojson` 9 个锚点 vs `brief/site-package/geometry/provisional_boundaries.geojson`（含/最近顶点距离）：

| 锚点 | 实测坐标（WGS84） | 命中类型 | 核验结果 |
|---|---|---|---|
| 五道口 | 39.991478, 116.331702 | railway/station（保留站房） | ⚠️ 不在 AI 原点社区 polygon 内（895m；polygon 在 116.342–116.353，偏东约 1km） |
| 大钟寺 | 39.967826, 116.331988 | amenity/place_of_worship（古钟博物馆） | ⚠️ 不在总体设计范围 polygon 内（899m）；**PROV-KEY-003（大钟寺）polygon 位于 39.944–39.950，比大钟寺本体/大钟寺站（≈39.968）南移约 1.8km** |
| 清华园车站 | 39.990237, 116.325602 | tourism/museum（站房旧址博物馆） | ✅ 在统筹研究范围内（距 AI 原点社区 polygon 最近 926m） |
| 五塔寺 | 39.943638, 116.323750 | amenity/place_of_worship（真觉寺，官方名） | ✅ 在统筹研究范围内（638m），紧邻西直门外大街 |
| 明光村 | 39.956632, 116.345969 | highway/bus_stop（学院南路） | ⚠️ 靠近大钟寺 polygon 但不在内（671m） |
| 知春路 | 39.975138, 116.321736 | highway/tertiary（路段代表点） | ✅ 在统筹研究范围内（1,150m）；代表点偏西段 |
| 清河站 | 40.040003, 116.309093 | railway/station（京张高铁清河站） | ✅ 位于北五环（40.026）以北 1.5km，符合"走廊北端外"定位 |
| 西直门外大街 | 39.937445, 116.337901 | highway/tertiary（路段代表点） | ✅ 距总体设计范围南边界 273m，与文字四至"南至西直门外大街"一致 |
| 学院路北端 | 39.999701, 116.346825（学院桥，OSM 命"学院路"最北节点） | highway/road | ⚠️ 与 AI 原点社区 polygon 670m；北四环以北延续"学清路"至 40.022415/116.344781（近上清桥） |

**结论**：文字四至关键线（西直门外大街、北五环、学院路 lon≈116.347）与实测锚点基本一致；**重点区 provisional polygon（尤其 PROV-KEY-002 偏东、PROV-KEY-003 偏南）与真实锚点存在 0.7–1.8km 级偏移**，维持 `provisional_rough` 纪律使用，等待 official 矢量（依申请公开路径）替换；锚点文件可作后续修正参考。

---

## ④ key 类 API 评估表（写清楚，不实测；文档信息以官方页面 2026-08-14 可访问为准）

| API | 数据内容（官方文档确认） | 对本项目价值 → GAP 映射 | 许可/合规要点 | 申请方式 | 优先级 | 配额/限制 |
|---|---|---|---|---|---|---|
| **天地图开放平台** `api.tianditu.gov.cn` | ① 地理编码 `geocoder`/逆地理编码（`ds={"keyWord":...}&tk=`）；② 行政区划 `administrative`（V2.0：中心点/轮廓/上级区划；V1.0 已于 2024-06-30 下线）；③ 地名搜索 V2.0 `search`（行政区划区域/视野内/周边/多边形/分类/普通搜索，返回 POI）；④ WMTS 矢量瓦片 `vec_c` 与影像底图 `img_c`（`tk` 必填） | ① 锚点/地名坐标校验（与 Nominatim 双源交叉）→ GAP-BOUNDARY 背景；② 海淀区/街乡轮廓背景参考（**非 official 边界**）→ GAP-BOUNDARY-001/002 背景；③ 设施 POI 底数 → **GAP-SERVICE-001**；④ 公开底图 → georeference/竞赛图件背景（background_reference） | 国家地理信息公共服务平台（天地图）服务条款；免费个人 key；成果公开使用须遵守《地图管理条例》（带审图号公益性地图/送审）；细则未逐条核验（**未验证**） | `passport.tianditu.gov.cn/register` 注册 → `console.tianditu.gov.cn/api/key` 申请 key（入口 2026-08-14 实测可访问；console 本机 HTTPS 握手失败，需浏览器操作） | **P0**（地理编码/行政区划/POI）；**P1**（瓦片，仅在需要影像底图时） | 免费 key 有配额与 QPS 限制，具体数值以控制台为准（**未验证**） |
| **高德开放平台** `restapi.amap.com` | ① 行政区域查询 `/v3/config/district`（可返回海淀区边界 polyline——背景参考）；② 搜索 POI `/v3/place/text`、`/v3/place/around`（学校/医院/商超/充电站等分类检索）；③ 地理/逆地理编码 `/v3/geocode/geo`、`/v3/geocode/regeo`；④ 交通态势 `/v3/traffic/status/road`（路况等级） | ① 海淀区边界参考（与文字四至/锚点对照）→ GAP-BOUNDARY 背景；② 设施点底数（学校/医院/商超/充电站）→ **GAP-SERVICE-001**（主要缓解项）；③ 坐标校验 → GAP-BOUNDARY 背景；④ 路况背景（拥堵/慢行分析素材，仅描述性）→ GAP-ROAD-001 背景 | 《高德地图开放平台服务协议》（页面标注 2025-12-03 更新）：免费与付费服务并存；调用量/QPS 受配额限制，超限请求返回无效结果；须遵守《地图管理条例》《地图审核管理规定》（公开地图标注审图号、不得删改版权声明）；**商用需商业授权**（本项目竞赛研究用途，非商用，仍建议以官方答复为准） | 注册高德开放平台 → 实名认证（个人开发者）→ 控制台创建应用 → 获取 Web 服务 Key | **P0** | 个人认证开发者与企业认证开发者调用量有差别（官网"流量限制说明"），具体数值未在本轮核验（**未验证**） |
| **百度地图开放平台** `lbsyun.baidu.com` | 位置搜索（行政区划搜索/周边/多边形搜索，3.4 亿 POI）、地理编码、路况（官方首页 2026-08-14 可见） | 高德备选 + 交叉验证 → GAP-SERVICE-001 / GAP-ROAD-001 背景 | 需注册认证；服务协议含配额与商用条款（本轮未逐条核验，**未验证**） | 免费注册/认证 → 控制台创建应用 → 获取 AK | **P2**（备选） | 免费额度，超限受限/收费（数值未验证） |
| **腾讯位置服务** `lbs.qq.com` | 地点搜索（8,000 万+ POI）、地址解析、WebService API（官方首页 2026-08-14 可见）；行政区划查询属 WebService 服务之一（**未逐一验证**） | 同百度（备选） → GAP-SERVICE-001 背景 | 服务条款含配额与商用条款（本轮未逐条核验，**未验证**） | 注册开发者 → 创建 Key | **P2**（备选） | 免费额度，具体以控制台为准（未验证） |

**实现建议（脚本落点）**：
- 新增 `scripts/fetch_facility_poi.py`：用高德（P0）`/v3/place/text` 按分类（学校 190000/医疗 090000/商超 060000/充电站 011100 等，分类码以官方 POI 分类表为准）在走廊 bbox（39.935–40.030, 116.310–116.395）拉取 POI → `data/processed/facility_poi_gaode.geojson`，限速+本地缓存，登记 `background_reference`。
- 新增 `scripts/fetch_adcode_haidian.py`（或并入上述脚本）：高德 `/v3/config/district`（keywords=海淀区, extensions=all）取海淀区边界 polyline → 与锚点/文字四至对照（背景参考）。
- 天地图地理编码可并入 `scripts/geocode_boundary.py` 同族：`scripts/geocode_anchors.py`（把本次 Nominatim 逻辑固化，加 `--provider` 参数支持天地图/高德双源交叉验证）。
- 北京开放平台数据集下载：`scripts/fetch_beijing_open_data.py`（登录后 userKey 调用，输出 `data/sources/beijing-data-open/`）。
- 所有新数据沿用项目纪律：来源/URL/日期/许可/CRS 登记 `data/source_registry.json`（由维护者执行），分级 `background_reference`/`official`（仅政务开放数据）。

---

## ⑤ 接入路线图

**本周（0 成本，已部分完成）**
- [x] Nominatim 9 锚点地理编码 → `data/processed/anchors_geocoded.geojson`（限速合规）
- [x] 锚点 × provisional 边界一致性核验（3 处偏移已记录）
- [x] data.beijing.gov.cn 匿名能力摸底 + 候选数据集与许可记录（`data/sources/beijing-data-open/`）
- [x] 天地图 WMS/WMTS 无 key 可用性确认
- [ ] 用户注册 data.beijing.gov.cn → 下载幼儿园名录/社区卫生服务中心/社会公用充电站（3 个小文件）→ 登记 source_registry（维护者）

**本月（免费 key 申请后）**
- [ ] 申请高德 key（P0）→ 拉取走廊设施 POI（学校/医院/商超/充电站）→ GAP-SERVICE-001 部分缓解
- [ ] 高德行政区域查询 → 海淀区边界背景参考，与锚点对照
- [ ] 申请天地图 key（P0）→ 地理编码双源交叉验证锚点；按需取 img_c 影像底图（georeference 参考）
- [ ] 若用户已注册北京开放平台 → 下载 3 数据集并筛选海淀记录

**有条件时（需要时再申请）**
- [ ] 百度/腾讯 key（P2 备选）：交叉验证 POI、路况背景
- [ ] 天地图 WMTS 瓦片底图（影像/矢量）— 仅当需要公开底图出图且满足审图要求
- [ ] 交通态势数据仅用于描述性背景（不得给出工程线位/施工可行性结论，GAP-ROAD-001 红线保持）

**始终不做**
- 涉密测绘（1:1万及以下地形图、宗地权属、地籍、竣工图）；商业地图数据标 official；把 POI/行政区划轮廓当作审批级红线。

---

## ⑥ 合规红线

1. **署名**：OSM/Nominatim 成果署名"© OpenStreetMap contributors"（ODbL）；北京开放平台成果注明"北京市公共数据开放平台"+ 按平台要求备案；天地图/高德成果若公开使用，按《地图管理条例》《地图审核管理规定》标注审图号（页面示例：审图号 GS(2011)6023号），竞赛内部提交按项目纪律注明来源即可。
2. **配额**：所有免费 key 有日配额/QPS 限制，脚本必须限速 + 失败退避 + 本地缓存去重；超限不硬冲、不批量刷；高德协议明确超限请求返回无效结果。
3. **不商用**：本项目为竞赛/研究用途，不用于商业发布；若后续公开部署/展览/媒体传播，须重新核对各平台商业授权（高德"认证开发商/商业授权"栏目）与地图审图要求。
4. **涉密不碰**：≤1:1万地形图及数字化成果（自然资发〔2020〕95号 秘密级）、宗地权属/地籍（须利害关系人）、竣工图一律不获取（沿用 `konggui-data-acquisition-plan` D 级纪律）。
5. **数据分级纪律**：`official`＝规自委/政府文件与政务开放数据（注明来源）；`background_reference`＝天地图 WFS/WMS、OSM/Nominatim、高德/百度/腾讯 POI 与行政区划轮廓；`provisional`＝推测边界。商业地图数据**永远**不升格为 official。
6. **不含个人信息**：本项目数据不涉及个人信息，不触发《个保法》处理规则（沿用计划 §六.6）。

---

## ⑦ 未验证项清单

| 项 | 状态 |
|---|---|
| 高德/天地图/百度/腾讯 免费 key 的具体日配额与 QPS 数值 | 未验证（以各控制台/流量限制说明为准） |
| 高德行政区域查询返回海淀区边界 polyline 的实际内容与坐标精度 | 未验证（需 key 实测，本轮不实测） |
| 天地图 console 控制台操作流程（本机 HTTPS 握手失败，需浏览器） | 未验证 |
| 腾讯位置服务行政区划查询 API | 未验证（首页未直接展开，属其 WebService 服务之一） |
| 天地图/百度/腾讯服务条款的商用与署名细则 | 未逐条核验 |
| 北京开放平台 3 个候选数据集的真实下载内容（需注册后下载） | 未验证（无匿名通道） |
| 高德 POI 分类码表（学校/医院/商超/充电站对应分类码） | 未验证（以官方 POI 分类表为准，接入时核对） |
| Nominatim 锚点在 2 个歧义锚点（清华园车站、学院路北端）之外其余 7 个是否命中"最准确要素" | 部分验证（取 limit=1 首条；如需更高置信可 review 每条候选） |
| WMTS `tiles.tianditu.gov.cn` HTTPS 握手失败原因（网络/客户端/服务端） | 未验证（t0 子域已确认 WAF 拦截） |

---

*本文实测部分全部由 curl 执行并留档（响应存 `/tmp/nominatim_anchors/`、`/tmp/bjdata_*.html`、`/tmp/tdt_*.xml` 等）；执行报告见会话交付。锚点成果文件 `data/processed/anchors_geocoded.geojson` 内已含署名与限速说明注释。*
