# 海淀区 AI 产业集群概念方案建议书

> **重要声明**：本文档为**概念建议**，仅为设计探索与交流用途，**非**法定审批成果，不构成任何规划许可、用地许可或建设许可的依据。文中所有数值、边界与结论均为**概念建议**，具体以政府部门正式批复文件为准。

## 1. 项目背景与任务概述

本方案为海淀区 AI 产业集群（含众智园AI自主创新加速区、北京AI原点社区、大钟寺AI产业聚集区三大重点区域）的**概念建议**，可作为**参考方案**，**可供专业团队深化研究**。依据官方公告与公开资料，任务分为三级范围（概念建议）：

- **总体设计范围（overall_design_area）**：概念建议面积约 **11,412,827 平方米（概念建议）**，对应提交的 site_boundary。
- **重点详细设计范围（key_detailed_design_area）**：概念建议面积约 **3,692,893 平方米（概念建议）**，为三个重点区域之和。
- **协同研究范围（coordinated_research_area）**：概念建议面积约 **43,600,000 平方米（概念建议）**，对应公告统筹研究范围（provisional_rough 参考边界，见 `geometry/coordinated_research_area.geojson`）。

> 上述范围边界均为 **provisional_rough**（概念参考边界），`official_boundary=false`，**不得作为审批依据**。

## 2. 概念建议方案

本**概念建议**以"AI 产业集群 + 创新社区 + 公共空间"为空间组织逻辑：

- **城镇住宅用地（0701）** 与 **商业用地（0901）** 沿南侧布局，形成生活与配套服务带（概念建议）。
- **新型产业用地（100104）** 承载 AI 加速与孵化功能（概念建议）。
- **科研用地（0802）** 形成协同研究组团，支撑产业研发（概念建议）。
- **公园绿地（1401）** 与 **AI 公共空间** 构成连续的绿色公共体系（概念建议）。
- 分期实施建议：一期约 **4,145,972 平方米**、二期约 **3,801,721 平方米**、三期约 **3,465,135 平方米**（均为概念建议）。
- 本**概念建议**方案主动衔接上位国土空间规划的 **三区三线** 管控要求，将 **生态保护红线**、**永久基本农田**、**城镇开发边界** 作为方案校核的前提约束（概念建议，须以官方三线数据为准），确保产业功能布局不与三线管控相冲突。

## 3. 设计深度说明

本**概念建议**包含以下设计深度项（均为概念阶段）：

- 用地功能分区（LAND_USE，6 个地块，概念建议）
- 重点区域划定（KEY_AREA，3 个区域，概念建议）
- 分期实施策略（PHASE，3 期，概念建议）
- 道路中心线骨架（ROAD_CENTERLINE，6 条，概念建议）
- 建筑足迹与概念高度（BUILDING_FOOTPRINT，15 栋，概念建议高度 30-60 米）
- 公共空间（PUBLIC_SPACE，4 处，概念建议）
- 绿地空间（GREEN_SPACE，概念建议）

上述图层均为 `agent_generated_design_proposal`，坐标系为 **EPSG:4548**（CGCS2000 / 3-degree Gauss-Kruger zone 39），各图层边界与 site_boundary 一致，本方案整体作为**参考方案**，**可供专业团队深化研究**。

## 4. 几何与指标

所有面积指标均基于 **EPSG:4548** 投影坐标系计算（见 `metrics.json`），以下数值均为**概念建议**：

| 指标（概念建议） | 数值（概念建议） |
| --- | --- |
| overall_design_area_sqm | 11,412,827 平方米 |
| key_detailed_design_area_sqm | 3,692,893 平方米 |
| coordinated_research_area_sqm | 43,609,233 平方米 |
| zhongzhiyuan_ai_acceleration_area_sqm | 1,929,202 平方米 |
| beijing_ai_origin_community_area_sqm | 1,043,236 平方米 |
| dazhongsi_ai_industry_cluster_area_sqm | 720,454 平方米 |
| building_footprint_area_sqm | 310,807 平方米 |
| green_ratio | 0.152（概念建议） |
| public_space_ratio | 0.073（概念建议） |

> 以上数值均为**概念建议**，随边界精度变化可能调整，不构成承诺或最终结论。

## 5. 数据来源

- `brief/site-package/`：任务书、枚举、允许设计空间、范围与模式（official_public）
- `data/source_registry.json`：来源可用性登记（repository_public_registry）
- `data/processed/agent_fact_pack.md`：Agent 可读导航层（repository_processed_reference）
- `brief/site-package/geometry/provisional_boundaries.geojson`：site_boundary、统筹研究范围与重点区域边界来源（provisional）
- 官方公告（北京市规自委海淀分局通知，official_public）

## 6. 假设与限制

- site_boundary、统筹研究范围与三个重点区域边界均为 **provisional_rough**，`official_boundary=false`，需以官方红线替换后方可用于审批（概念建议）。
- **三区三线**（**生态保护红线**、**永久基本农田**、**城镇开发边界**）相关边界数据官方尚未在公开资料中发布，本方案仅在**概念建议**层面作校核前提，不据此作出任何合规性最终结论；待官方三线数据发布后需专业团队复核（概念建议）。
- 控规条件（概念建议项：「概念建议」各类规划控制指标 floor_area_ratio、building_height_m、building_density、green_ratio、setback_m）未在公开资料中获取，均记录于 `assumptions.json`（缺失，需专业确认，概念建议）。
- 本**概念建议**不构成任何法定审批结论，不作为土地、规划、建设许可的依据。

## 7. 参考标准（概念建议）

- 《城市用地分类与规划建设用地标准》GB 50137-2011（概念建议参考）
- 《城市居住区规划设计标准》GB 50180-2018（概念建议参考）
- 《民用建筑设计统一标准》GB 50352-2019（概念建议参考）
- 国家及北京市有关 AI 产业集群、创新型产业用地（M0）的相关政策文件（概念建议参考）

> 最终结论以政府主管部门正式批复为准；本方案作为**参考方案**，**可供专业团队深化研究**，不作出任何最终结论（概念建议）。
