# 天地图 WFS 北京范围取数记录

- 服务：`https://gisserver.tianditu.gov.cn/TDTService/wfs`（无需 key，公开服务）
- 获取日期：2026-08-13
- 权威分级：`background_reference`（国家基础地理信息中心 NGCC 公开数据，1:100 万公众版；
  登记 source_id `DATA-SRC-TIANDITU-WFS-1M`，许可与用途限制见 `data/source_registry.json`）
- 输出文件：`data/processed/tianditu_wfs_beijing.geojson`

## 请求方式（实测）

- `GetCapabilities`：HTTP 200，共 10 个图层：AANP、AGNP（注记）、BOUA、BOUL（境界）、
  HYDA、HYDL（水系）、LRDL、LRRL（道路铁路）、RESA、RESP（居民地）。
- `GetFeature`：`service=WFS&version=1.1.0&request=GetFeature&typeNames=TDTService:{layer}`
  `&bbox={minLat,minLon,maxLat,maxLon}&outputFormat=application/json`
  - 注意：**bbox 轴顺序为 纬度,经度**（lat,lon），即使 DefaultCRS 为 EPSG:4326；
    按 经度,纬度 传参会返回 0 要素（实测）。
  - 返回 JSON：`FeatureCollection`，`crs=urn:ogc:def:crs:EPSG::4326`，坐标为经纬度
    （样例：阜成门北大街 `[116.3503, 39.9060]`）。

## 取数范围与要素数

- 北京范围 bbox：`39.4,115.4,41.1,117.5`（覆盖北京市域及其紧邻的河北县界切片，
  如涞水县、三河市等，系 bbox 矩形切割所致）。
- 六图层要素数（合并后共 **3148** 个要素，文件 6.18 MB）：

| 图层 | 含义 | 要素数 |
|---|---|---|
| LRDL | 道路（含高速/国道/辅路等） | 1750 |
| HYDL | 水系线 | 1031 |
| LRRL | 铁路（含京广高铁等） | 167 |
| BOUL | 境界线 | 105 |
| BOUA | 行政境界面 | 50 |
| HYDA | 水系面 | 45 |

- 各要素 `properties` 保留原始字段（OBJECTID/GB/RN/NAME/RTEG/TYPE/Shape_Leng/Shape_Area/PAC 等），
  并追加 `tdt_layer` 字段标明来源图层。
- 几何类型：MultiLineString 3053、MultiPolygon 95；坐标均在 70–140E / 10–55N 内（脚本校验通过）。

## 用途限制（按 source_registry 登记）

- 仅作 overview 底图/背景层、粗略上下文、georeference 参考；不得作为 official redline、
  精确面积计算、道路中心线几何依据，不得作为独立数据产品再分发。
- 成果公开使用须履行地图审核并标注审图号（参考 webmap.cn 1:100 万公众版，审图号 GS(2016)2556号）。
