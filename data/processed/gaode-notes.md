# 高德开放平台数据采集说明（2026-08-15）

> 执行：scripts/fetch_gaode.py ｜ Key：Web 服务（个人开发者，无安全密钥/jscode）
> 依据：docs/map-api-assessment-2026-08-14.md（P0 接入方案）
> 纪律：background_reference，不替代 official 边界/指标；不商用（竞赛/研究）

## 一、产出

| 文件 | 内容 | 规模 |
|---|---|---|
| `data/processed/facility_poi_gaode.geojson` | 走廊设施 POI（EPSG:4326） | **792 个**：学校 207 / 医疗 200 / 商超 198 / 充电站 187 |
| `data/processed/haidian_district_gaode.geojson` | 海淀区行政边界（EPSG:4326） | 1 Polygon，1831 点，bbox 116.043–116.389, 39.886–40.160 |

- 走廊 bbox：116.310–116.395, 39.935–40.030（统筹研究范围外扩，沿用评估文档）
- POI 分类：医疗 090000 / 商超 060000 / 充电站 011100 走 `/v3/place/polygon`
  （分页 offset=25，去重 poiid）；**学校不走 polygon**——实测 `/v3/place/polygon
  types=190000` 返回大量"地名地址信息"（立交桥/道路名）垃圾，改用
  `/v3/place/text types=中文类名`（学校/小学/幼儿园/职业技术学校）**city=海淀区**分页（绕开北京市 600 条相关性上限）+
  走廊 bbox 客户端过滤 + 类型串过滤（须含"学校"）→ 207 个（高校 46/小学 51/幼儿园 60/中学 19/职校 14/学校 13）
- 接口：`/v3/place/polygon`、`/v3/place/text`、`/v3/config/district`
- 限速 ≥1s/请求，共约 60 次请求，无配额报错

## 二、坐标与 CRS

高德返回 GCJ-02 → 已用标准算法近似逆变换为 WGS84（EPSG:4326），误差数米。
每个要素 properties 含 `crs_source` 标注；metadata.crs_note 声明。本项目其他图层
（OSM/Nominatim/天地图）均为 WGS84，未混用坐标系。

## 三、用途映射

- 设施 POI → **GAP-SERVICE-001 部分缓解**（学校/医院/商超/充电站底数背景）
- 海淀区边界 → GAP-BOUNDARY-001/002 背景参考（与锚点/文字四至对照）
- 全部为 `background_reference`，**不得**作为 official 红线、审批依据或精确面积复算依据

## 四、合规

- 成果署名 © 高德地图（高德开放平台 Web 服务）；竞赛/研究用途不商用
- 免费 key 有日配额/QPS 限制，脚本已限速；超限重试退避
- 公开使用按《地图管理条例》标注审图号（内部提交按项目纪律注明来源即可）
- 不申请商业授权场景；不将 POI/行政区划轮廓当作审批级红线

## 五、已知局限

1. **覆盖以高德 POI 库为准**：polygon 搜索按分类分页返回，总数受高德库与分页上限
   影响；缺漏不代表现实不存在（与 OSM 底数可交叉）。
2. 学校类经文本搜索（学校/小学/幼儿园/职业技术学校 4 类名，city=海淀区）+
   bbox/类型串过滤得 207 个（高校 46/小学 51/幼儿园 60/中学 19/职校 14/学校 13），
   零地名污染；中学 19 较此前 city=北京市 的 7 个显著改善。
3. 高德边界轮廓为背景参考，非官方红线；精确边界以规自委 official（依申请公开）为准。
4. 坐标经 GCJ-02→WGS84 近似转换，数米级误差；不得用于红线/审批级精度用途。
5. Key 配置存 `data/config/gaode_keys.local.json`（已 gitignore，不入库）。
