# 天地图·北京 标准地图下载记录（海淀区 / 中心城区 / 北京市）

- 下载日期：2026-08-14
- 来源页面：`https://beijing.tianditu.gov.cn/bzdt/`（GET HTTP 200；HEAD HTTP 403，属预期）
- 权威分级：`background_reference`（北京市规划和自然资源委员会发布、北京市测绘设计研究院技术支持；
  免费下载 JPG/PDF；**无 EPS/TIF**，与 2026-08-13 前期实测一致）
- 文件目录：`data/sources/tianditu-bzdt/`（`lib/` 下为原始 zip 包，外层为解压件）

## 一、接口实测结果（2026-08-14 复核）

1. **列表接口**（页面 JS 渲染，`js/standardMap.js` 内发现真实请求格式，见 `/tmp/standardMap.js:129`）：
   - `GET /bzdt/standardmap.do?local=<地域>&color=<色彩>&version=<版本>` → HTTP 200，纯文本，
     **每 8 行一条记录**（组名行 + 7 个字段），字段顺序：
     `地图标题(年份版)` / `比例尺` / 色彩(`cs`彩色|`ds`单色) / 预览图 `./img/xxx.png` /
     下载包 `./lib/xxx.zip` / 查看量 / 下载量。
   - 实测参数值（取自页面 `navdown1/2/3` 导航）：
     - `local`（地域）：`all1` 全选、`qsy` 全市域、`zxcq` 中心城区、`hxq` 核心区、`bjcsfzx` 副中心、
       各区拼音缩写（`hdq` 海淀区、`dcq` 东城、`xcq` 西城、`cyq` 朝阳、`ftq` 丰台、`sjsq` 石景山、
       `mtgq` 门头沟、`fsq` 房山、`tzq` 通州、`syq` 顺义、`dxq` 大兴、`cpq` 昌平、`pgq` 平谷、
       `hrq` 怀柔、`myq` 密云、`yqq` 延庆）
     - `color`：`all2` 全选、`cs` 彩色、`ds` 单色
     - `version`：`all3` 全选、`2025`/`2024`/`2023`/`2021`/`2020`/`2019`/`2016`
   - 实测查询：`local=hdq&color=cs&version=2025` → 命中「海淀区(2025年版) 1:12万 彩色」；
     `local=qsy&color=cs&version=2025` → 全市域 1:50万/1:25万/1:100万/1:80万；
     `local=zxcq&color=cs&version=2025` → 中心城区 1:9万/1:12.5万/1:18万/1:25万/1:36万。
2. **下载包直链**：`GET /bzdt/lib/<包名>.zip` → HTTP 200，`application/zip`，无需登录。
   `downloadCount.do?href=./lib/xxx.zip` 仅做下载量计数（返回新计数），**不返回下载地址**。
3. 包内构成：JPG + PDF 各一（无 EPS/TIF）。

## 二、下载文件清单（全部 `file` 验真）

| 文件 | 大小 | file 验真 | 内容 |
|---|---|---|---|
| `data/sources/tianditu-bzdt/lib/hdq2025_12w_1.zip` | 2,618,652 B | Zip archive（deflate），`unzip -t` 通过 | 海淀区 2025 彩色 1:12万 |
| `data/sources/tianditu-bzdt/lib/zxcq2025_9w_1.zip` | 10,005,187 B | Zip archive（deflate），`unzip -t` 通过 | 中心城区 2025 彩色 1:9万 |
| `data/sources/tianditu-bzdt/lib/bj2025_50w_1.zip` | 3,997,598 B | Zip archive（deflate），`unzip -t` 通过 | 北京市 2025 彩色 1:50万 |

解压件（单文件均 <8MB，故 JPG 与 PDF 一并保留）：

| 文件 | 大小 | 验真 | 分辨率/页面 |
|---|---|---|---|
| `hdq2025_12w_1.jpg` | 1,291,938 B | JPEG baseline 8bit CMYK | 1731×2541 px |
| `hdq2025_12w_1.pdf` | 1,614,854 B | PDF v1.5，1 页 | 页面 830.99×1219.72 pt（约 29.3×43.0 cm） |
| `zxcq2025_9w_1.jpg` | 5,674,296 B | JPEG baseline 8bit CMYK | 3750×3361 px |
| `zxcq2025_9w_1.pdf` | 5,076,232 B | PDF v1.5，1 页 | 页面 1799.87×1613.06 pt（约 63.5×56.9 cm） |
| `bj2025_50w_1.jpg` | 2,207,444 B | JPEG baseline 8bit CMYK | 2740×2423 px |
| `bj2025_50w_1.pdf` | 2,173,726 B | PDF v1.5，1 页 | 页面 1315.10×1162.85 pt（约 46.4×41.0 cm） |

下载源 URL（均为 2026-08-14 实测 HTTP 200）：
- `https://beijing.tianditu.gov.cn/bzdt/lib/hdq2025_12w_1.zip`
- `https://beijing.tianditu.gov.cn/bzdt/lib/zxcq2025_9w_1.zip`
- `https://beijing.tianditu.gov.cn/bzdt/lib/bj2025_50w_1.zip`

## 三、审图号核验（页脚 vs 地图本体）

- **页面页脚**：`京S(2025)004号` —— 仅网站版权号（页面 HTML `bottom_info` 中与京ICP备09070668号并列）。
- **地图本体**：三幅 PDF 内 `pdftotext` 提取均为 **`审图号:京S(2025)041号`**，
  出品栏「北京市规划和自然资源委员会」。即此前推测的"地图本体可能是京S(2025)041号"**已核实**。
- 地图正式标题（PDF 文本层）：`北京市行政区域界线基础地理底图(海淀区)` / `(中心城区)` / `(全市)`。

## 四、覆盖范围与京张走廊核验（pdftotext 文本层）

- **海淀区 1:12万**：覆盖整个海淀区（含昌平/怀柔/密云接边注记）；文本层出现清河、中关村、学院路、上地、清华、G7（京藏高速）——京张走廊（北五环—西直门、万泉河路—京藏高速）**整体位于图内**。
- **中心城区 1:9万**：三幅中分辨率最高（3750×3361 px）；文本层出现清河×3、西直门×2、清华×2、蓟门×2、知春路、西土城、明光、上地、中关村——走廊南北两端锚点（西直门/清河）均在图内，**为走廊单图最佳底图**。
- **北京市 1:50万**：全市域宏观底图。
- 注：地图部分地名为曲线注记，`pdftotext` 仅能提取文本层子集（如五道口/大钟寺未出现在提取结果中），上述核验以出现的要素为准，不构成"图上没有"的结论。

## 五、坐标基准说明

- 三幅图 PDF 文本层**未标注坐标系/投影**（正文仅标题、比例尺、审图号、出品单位）。
- 按全国标准地图服务惯例（2018-07-01 起新编地图须采用 CGCS2000），天地图·北京标准地图应为
  **CGCS2000 国家大地坐标系**——**未在图面证实，标注"未验证"**；georeference 时必须用
  `data/processed/tianditu_wfs_beijing.geojson`（EPSG:4326）或 OSM 同名地物双源交叉验证后定基准。

## 六、可用于 georeference 的说明

- 均为单页整幅制图（PDF 无内嵌叠加要素的复杂分层，JPG/PDF 内容一致），图面无变形格网干扰，
  适合 QGIS Georeferencer / `gdal_translate -gcp` 做仿射或 TPS 配准。
- 推荐顺序：**中心城区 1:9万**（走廊细部，GCP 取知春路—学院路、西土城路、清河、西直门等交叉点）
  > 海淀区 1:12万（全走廊）> 北京市 1:50万（宏观示意）。
- 名义精度：1:9万 / 1:12万 图幅，按图上 0.2mm 可读性约为 18–24m 级；配准后 RMSE 目标 <5m（方案级），
  **不得宣称优于底图名义精度**。
- 处理前需确认导出坐标基准（见 §五）；面积复算一律 EPSG:4548（CGCS2000 3°GK 39 带）。
- 用途限制（按 source_registry `background_reference` 纪律）：仅作底图/背景参考与 georeference 基准，
  不作 official redline、不作精确面积计算依据；公开展示须标注审图号京S(2025)041号。
