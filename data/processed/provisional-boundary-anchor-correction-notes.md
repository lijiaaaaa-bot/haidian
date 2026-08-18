# provisional 重点片区边界锚点修正记录（2026-08-14）

> 依据：`docs/map-api-assessment-2026-08-14.md` §3 锚点核验结果 + `data/processed/anchors_geocoded.geojson`（Nominatim/Overpass 实测，© OpenStreetMap contributors, ODbL 1.0）
> 执行脚本：`scripts/correct_provisional_boundaries.py`（幂等，`--revert` 可回退）

## 一、问题与修正

Nominatim 实测锚点显示两处重点片区 provisional polygon 与真实地名锚点存在
0.7–1.8km 级偏移。本次对三个几何文件中的对应 feature 做刚性平移（形状与
面积不变），使锚点落入各自多边形：

| Feature | 锚点（实测） | 旧位置 | 平移量 | 修正后 |
|---|---|---|---|---|
| PROV-KEY-002（北京AI原点社区） | 五道口站 116.33170, 39.99148 | lon 116.342–116.353（偏东约 1km，锚点距旧多边形 895m） | Δlon **-0.0110°** | lon 116.331–116.342，五道口约 60m 入界 |
| PROV-KEY-003（大钟寺AI产业聚集区） | 大钟寺本体 116.33199, 39.96783 | lat 39.944–39.94984（南移约 1.8km） | Δlat **+0.0209°**、Δlon **-0.0101°** | lat 39.9649–39.97074，大钟寺本体纬度居中、经度近西界内 |
| PROV-KEY-SCOPE-001（三区汇总） | — | 内嵌 002/003 子多边形与旧坐标逐点相同 | 按坐标匹配随 002/003 同步平移 | 与分区一致 |

**面积校验**（球面近似，平移固有数值偏差 ≤0.031%，真实面积不变）：
- PROV-KEY-002：1,042,053 → 1,042,053 m²（0.0000%）
- PROV-KEY-003：719,643 → 719,424 m²（-0.0306%，近似公式纬度平移偏差）

## 二、修正后锚点校验（射线法 point-in-polygon）

- 五道口 (116.3317017, 39.9914779) ∈ PROV-KEY-002 ✅
- 大钟寺 (116.3319879, 39.9678257) ∈ PROV-KEY-003 ✅

## 三、已知剩余偏差（保持 provisional_rough 纪律，不掩盖）

1. **明光村**（39.9566, 116.3460）仍在 PROV-KEY-003 以南（纬度界外）；修正前亦在界外（671m），非本次引入。
2. **PROV-KEY-002/003 西移后超出 SITE（总体设计范围）西界约 0.008–0.009°**（约 700–800m）。SITE 西界本身为文字四至（"西至大钟寺东路荷清路"）粗略边界，未做锚点核验修正；SITE 西界在五道口/大钟寺一带的真实位置需 official 矢量确认。
3. 大钟寺站（13 号线）与五道口站同属修正后多边形近界位置，站台实际占地未核对。
4. 以上全部仍为 **provisional / provisional_rough**，不得作为 official 红线、审批依据或精确面积复算依据；**official 矢量替换路径不变**（依申请公开，见 `docs/konggui-data-acquisition-plan-2026-08-13.md`、`docs/info-disclosure-application-2026-08-13.md`）。

## 四、更新文件（三份同源拷贝 + 元数据）

- `brief/site-package/geometry/provisional_boundaries.geojson`（源）
- `brief/site-package/geometry/provisional_boundaries_upgraded.geojson`
- `submissions/test/key_areas_boundary.geojson`

每个被修正 feature 的 properties 增加：

```json
"anchor_corrected": true,
"anchor_correction": {
  "date": "2026-08-14",
  "basis": "<锚点名>（<OSM 类型>，<坐标>）",
  "reported_offset": "<报告记录的偏移>",
  "shift_deg": "<平移量>",
  "residual_notes": "<剩余偏差>",
  "method": "rigid translation preserving shape and area",
  "source": "data/processed/anchors_geocoded.geojson（© OpenStreetMap contributors, ODbL 1.0）",
  "still_provisional": true
}
```

## 五、未做（明确范围外）

- 未修正 SITE / RESEARCH 边界（报告未标记其锚点偏移；西直门外大街、北五环、学院路等文字四至与锚点一致）。
- 未修正 PROV-KEY-001（众智园，无锚点偏移报告；其南界 40.0075 距学院桥锚点 39.9997 约 0.9km，属正常相邻关系，未标记）。
- 未将任何 provisional 数据升格为 official；未触碰 `data/source_registry.json` / `source-registry-data.js`（维护者统一登记）。
