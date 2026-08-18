# OSM Overpass 采集记录：京张走廊现状底数（background_reference）

> 数据来源：OpenStreetMap（ODbL 1.0）。**使用与再分发必须署名 OpenStreetMap contributors**。
> 权威分级：`background_reference`（对应 source_id `DATA-SRC-OSM`，仅作现状底数/背景层，
> 不得作为 official 红线、规划边界或精确面积计算依据；现有 OSM 路网文件
> `osm_road_network.geojson` 不在本次重复采集范围）。

## 获取方式

- 端点：`POST https://overpass-api.de/api/interpreter`（无需 key），`out geom` 输出全几何。
- 获取日期：2026-08-14（北京时间 09:26–09:31；UTC 01:26–01:31）。
- 数据快照：`osm3s timestamp_osm_base ≈ 2026-08-14T01:27:35Z`（各 query 快照略有先后）。
- 查询次数：**5 次**（预算 ≤6）；相邻 query 间隔 ≥6 秒（要求 ≥5 秒）；失败重试 1 次。
- 坐标：EPSG:4326（WGS84），输出坐标统一简化至 **6 位小数**（约 0.1 m）。

## 采集范围

- bbox 取自 `brief/site-package/geometry/study_area_bbox.geojson`：
  **south=39.935, west=116.3, north=40.055, east=116.395**（约 119 km²，含走廊及两侧上下文）。
- 铁路车站/名称锚点查询 bbox 外扩 2 km：
  south=39.917, west=116.2766, north=40.073, east=116.4185。

## 查询日志

| # | 查询 | HTTP | 耗时 | 结果 |
|---|---|---|---|---|
| 1 | 建筑 `way["building"]` [timeout:120] | 504 | 12 s | 服务器繁忙（dispatcher timeout），重试 |
| 2 | 公共服务 `nwr[amenity~…]` [timeout:120] | 200 | 14.1 s | 1920 要素 |
| 3 | 铁路 `way["railway"]` + 站点/名称节点 [timeout:120] | 200 | 9.4 s | 609 要素 |
| 4 | 绿地 `nwr[leisure~…]` + `nwr[landuse~…]` [timeout:120] | 200 | 43.1 s | 2097 要素 |
| 5 | 建筑重试（改用 [timeout:180]） | 200 | 157 s | 13255 条 way（原始） |

- 首次建筑查询 504 为公开实例繁忙所致（非查询超时）；按任务约定以 `[timeout:180]` 重试成功。
- 未使用镜像端点（kumi.systems / maps.mail.ru）；原始响应留存在 `/tmp/osm_overpass_raw/`（临时目录，未入库）。

## 输出文件与要素数

| 文件 | 层 | 要素数 | 几何 | 大小 |
|---|---|---|---|---|
| `osm_buildings_corridor.geojson` | OSM_BUILDINGS | 4000（原始 13255，≥60㎡ 12824，按面积取 top 4000） | Polygon | 2.56 MB |
| `osm_public_facilities_corridor.geojson` | OSM_PUBLIC_FACILITIES | 1920（node 1422 / way 476 / relation 22） | Point | 0.89 MB |
| `osm_railway_corridor.geojson` | OSM_RAILWAY | 609（线 430 / 点 179） | LineString / Point | 0.37 MB |
| `osm_green_spaces_corridor.geojson` | OSM_GREEN_SPACES | 2097（Polygon 2050 / Point 33 / LineString 14） | 混合 | 1.44 MB |

每个文件的 FeatureCollection 顶层含 `attribution: "© OpenStreetMap contributors, ODbL 1.0"` 外键成员。
所有要素属性统一含 `source: "DATA-SRC-OSM"`、`official_boundary: false`、`usable_for_formal: "background_only"`、`precision_note`。

## 字段说明

- **osm_buildings_corridor.geojson**（GAP-BUILDING-001 现状建筑底数）：
  `osm_id`（way id）、`building`（建筑类型，如 yes/apartments/university/school/commercial…）、
  `name`、`height`（仅 56 条有值）、`area_m2`（本地等距投影 shoelace 计算）。
  分布：面积中位 1583 m²、合计 9.41 km²；`university` 212 条（清华/北大等大院建筑量大）。
- **osm_public_facilities_corridor.geojson**（GAP-SERVICE-001 公共服务设施部分底数）：
  `osm_id`、`osm_type`（node/way/relation）、`name`、`amenity`、`shop`、`operator`。
  面/线要素取质心为 Point。前几类：restaurant 722、bank 216、cafe 191、fast_food 171、
  school 170、hospital 53、university 50、kindergarten 47、college 45、library 39、
  police 33、place_of_worship 33、pharmacy 27、post_office 26、charging_station 26。
- **osm_railway_corridor.geojson**：
  线要素 `osm_id`、`railway`（subway 187 / rail 115 / platform 86 / razed 18 / disused 17 /
  abandoned 1 / station 5 / signal_box 1）、`name`；
  点要素 `node_type` = `station`（地铁站等 110）/ `historical_station_candidate`（1）/
  `name_match`（68），另含 `abandoned_railway`、`railway_ref`、`railway_position`。
- **osm_green_spaces_corridor.geojson**：
  `osm_id`、`osm_type`、`name`、`leisure`（park 253 / garden 137 / pitch 743 / sports_centre 48 /
  stadium 40 / playground 21…）、`landuse`（grass 422 / forest 420 / recreation_ground 16 /
  village_green 1）。闭合环→Polygon，开放线→LineString，node→Point。

## 京张铁路遗迹锚点（清华园车站旧址）

- 命中 **node 1364084981**：`abandoned:railway=station`，`name=清华园`，
  `railway:position:exact=16.515`（京张线里程），`node_type=historical_station_candidate`。
  为清华园车站旧址在 OSM 中的锚点，位置精度数米级，**需与文保单位公布范围现场/图纸核验后使用**。
- 另有 `railway=razed`（18 条）与 `railway=disused`（17 条）线要素，对应京张线拆除/停用段遗迹。
- 名称匹配（清华园|五道口|大钟寺，bbox 外扩 2 km）命中含大量同名无关 POI（如清华园宾馆、
  五道口工人俱乐部、大钟寺派出所等），已全部保留在 `node_type=name_match`，使用时按语义筛选。

## 质量说明（必须阅读）

1. **OSM 社区数据，覆盖不均匀**：缺漏/未标绘不代表现实中不存在。商业设施、小建筑、
   高校内部要素的完整度低于官方测绘成果；本数据仅作现状底数背景，禁止用作 official。
2. **建筑**：仅按任务规格取 `way["building"]`，不含 relation（multipolygon）型建筑；
   已按 >60 m² 过滤，且因 >4000 条**按面积取 top 4000**（丢弃 8824 条中小建筑，保留面积 ≥约 1030 m²），
   如需全量小建筑纹理可用 500m 网格抽样重新生成。
3. **铁路线**：返回与 bbox 相交 way 的**完整几何**，线要素可能延伸至 bbox 之外（实测范围
   lon 116.12–116.55，lat 39.82–40.08），属 Overpass 正常行为；站点节点在 2 km 外扩 bbox 内。
4. **绿地**：landuse=forest 等面在 bbox 边缘同样存在越界几何；与建筑/道路无拓扑一致性保证。
5. 各文件坐标范围大体落在 bbox（建筑/绿地/POI 均有少量越界点，为跨越 bbox 边界要素的完整几何）。

## 署名与合规（强制）

- 引用/展示本数据须标注：**© OpenStreetMap contributors**，许可 **ODbL 1.0**
  （https://www.openstreetmap.org/copyright）。
- 不得标注为 official；不得作规划红线、精确面积计算、道路中心线依据。
- 不修改 `data/source_registry.json`（OSM 条目 DATA-SRC-OSM 的登记范围以既有路网文件为准，
  本批文件同源同许可，扩展其 local_paths 的登记留待人工维护）。
