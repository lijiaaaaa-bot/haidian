#!/usr/bin/env python3
"""Generate urban design submission from facts using DeepSeek V4 Flash.

Reads the design brief, task book, fact pack, and CSVs, then asks DeepSeek
to generate complete GeoJSON geometry + proposal.md + metrics.json in one shot.

Usage:
    python3 scripts/deepseek_design.py submissions/test/ds-gen
"""

from __future__ import annotations

import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_facts() -> str:
    """Load all facts into a single prompt context."""
    parts = []

    # Core design brief
    brief = json.loads((ROOT / "brief/site-package/design_brief.json").read_text())
    parts.append("# 设计任务书\n" + json.dumps(brief, ensure_ascii=False, indent=2))

    # Agent task book
    taskbook = json.loads((ROOT / "brief/site-package/agent_taskbook.json").read_text())
    parts.append("# Agent 任务书\n" + json.dumps(taskbook, ensure_ascii=False, indent=2))

    # Fact pack
    fact_pack = (ROOT / "data/processed/agent_fact_pack.md").read_text()
    parts.append("# 事实包\n" + fact_pack)

    # CSVs
    for name in ["project_scope_summary.csv", "agent_task_requirements.csv",
                 "source_use_matrix.csv", "missing_data_checklist.csv"]:
        p = ROOT / "data/processed" / name
        if p.exists():
            parts.append(f"# {name}\n" + p.read_text())

    # Source registry
    sources = json.loads((ROOT / "data/source_registry.json").read_text())
    parts.append("# 资料来源\n" + json.dumps(sources, ensure_ascii=False, indent=2))

    # Land use enums
    enums = json.loads((ROOT / "brief/site-package/enums/land_use_codes.json").read_text())
    parts.append("# 用地分类代码\n" + json.dumps(enums, ensure_ascii=False, indent=2))

    # Provisional boundaries (reference only)
    bounds = json.loads((ROOT / "brief/site-package/geometry/provisional_boundaries.geojson").read_text())
    # Sample coordinates to keep prompt size reasonable
    for f in bounds["features"]:
        geom = f.get("geometry", {})
        if geom.get("type") == "Polygon":
            geom["coordinates"] = geom["coordinates"][:1]  # keep first ring
            if geom["coordinates"] and geom["coordinates"][0]:
                ring = geom["coordinates"][0]
                if len(ring) > 6:
                    geom["coordinates"][0] = ring[:4] + [ring[-1]]  # first 4 + last
    parts.append("# 临时边界（参考，可适度调整顶点）\n" + json.dumps(bounds, ensure_ascii=False, indent=2))

    return "\n\n---\n\n".join(parts)


def build_prompt(facts: str, submission_path: str) -> str:
    """Build the generation prompt."""
    return f"""你是城市设计AI。基于以下事实资料，为百年京张AI创新带生成完整的城市设计方案包。

{facts}

---

## 你的任务

为上述项目生成完整的城市设计提交包。输出一个 JSON 对象，包含以下所有文件的内容。

### 输出格式
```json
{{
  "files": {{
    "geometry/site_boundary.geojson": <GeoJSON FeatureCollection: 1 SITE_BOUNDARY feature, site is ~11.4km² along 京张 corridor, approximate bbox 116.340-116.355, 39.94-40.03>,
    "geometry/key_areas.geojson": <GeoJSON FeatureCollection: 3 KEY_AREA features (众智园~192ha north, 北京AI原点社区~104ha middle, 大钟寺AI产业聚集区~72ha south)>,
    "geometry/land_use.geojson": <GeoJSON FeatureCollection: 8-12 land_use polygons with differentiated land_use_codes from the enum list, coverage ~11.4km²>,
    "geometry/buildings.geojson": <GeoJSON FeatureCollection: 8-15 BUILDING_FOOTPRINT features of varying sizes, heights (15-120m), and types, placed within land_use zones>,
    "geometry/roads.geojson": <GeoJSON FeatureCollection: 6-12 ROAD_CENTERLINE segments forming a real network connecting the 3 key areas along 京张 corridor>,
    "geometry/green_space.geojson": <GeoJSON FeatureCollection: 4-8 green/public space polygons along 清河/小月河 corridors, ~12% of site area>,
    "geometry/public_space.geojson": <GeoJSON FeatureCollection: 3-6 public open space polygons, ~7% of site area>,
    "geometry/phasing.geojson": <GeoJSON FeatureCollection: 3-4 phase polygons (phase 1: key areas, phase 2: corridors, phase 3: expansion)>,
    "geometry/constraints.geojson": <GeoJSON FeatureCollection: 0-2 constraint features (existing_water: 清河/小月河, existing_rail: 京张铁路 corridor)>,
    "proposal.md": <Markdown: 12 chapters per the taskbook, each ≥500 chars, citing [source:...]/[data:...]/[metric:...], Chinese>,
    "metrics.json": <JSON: site_area_sqm, building_footprint_area_sqm, green_ratio, public_space_ratio, key_area_count, with formulas and source_files>,
    "agent.json": <JSON: agent card with model info, task compliance summary>,
    "assumptions.json": <JSON: list of assumptions about missing regulatory data>,
    "self_check.json": <JSON: 5-6 self-check items, all pass>,
    "compliance_matrix.json": <JSON: 23 requirement entries with per-requirement differentiated sections/layers/metrics>,
    "sources.json": <JSON: source registry with used sources and authority levels>
  }}
}}
```

## 设计约束

1. **坐标系**: 所有几何使用 EPSG:4326 (lon/lat)。面积在 EPSG:4548 投影下计算。坐标必须在 lon[116.33-116.36], lat[39.94-40.03] 范围内。

2. **Provisional boundary**: site_boundary 必须标记 official_boundary=false, geometry_role="provisional_constraint", boundary_precision="provisional_rough"。不要声称是官方红线。

3. **用地分类**: 从提供的 land_use_codes 枚举中取值。用地应体现三区差异化——众智园偏研发/教育(08), 北京AI原点社区偏商业/混合(09), 大钟寺偏产业/办公(09/10)。

4. **建筑**: 每个 feature 必须有 id, layer=BUILDING_FOOTPRINT, source_type=agent_generated_design, confidence=medium, geometry_role=design_proposal, building_type, name_zh, height_m (15-120m), area_sqm_declared。建筑不应全是相同高度。

5. **道路**: road_class 取值 main_road/secondary_road/greenway。路网应连通三个重点区。每个 feature 必须有 layer=ROAD_CENTERLINE。

6. **绿地/公共空间**: green_space 沿清河/小月河廊道分布。layer=GREEN_SPACE / PUBLIC_SPACE。

7. **Proposal**: 12 个必写章节（设计依据与资料清单、三层范围工作框架、统筹研究范围产业与未来城市研究、总体设计范围城市更新与控规深度城市设计、重点区域详细设计、AI创新生态人才画像与AI+场景、用地建筑规模与拆改留方案、交通轨道市政与公共服务设施、蓝绿空间公共空间与城市风貌、更新项目清单实施政策与分期计划、指标体系面积复算与合规矩阵、风险版权与合规说明）。每章必须有实质性内容（不是"方案应..."的模板语），必须引用 [source:...] 或 [data:...] 证据。

8. **指标**: site_area_sqm ~11,412,825, green_ratio ~0.12, public_space_ratio ~0.07, building_footprint_area_sqm 从实际几何面积计算。每个指标必须有 formula 和 source_files。

## 重要

- 输出完整的 JSON 对象——不要省略、不要 "..."
- GeoJSON coordinates 必须是有效的数字数组
- proposal.md 内容是中文 Markdown
- 所有 JSON 字符串必须正确转义（proposal.md 中的引号、换行符）
- 不要用 markdown 代码块包裹输出——直接输出纯 JSON
"""


def call_deepseek(prompt: str) -> dict:
    """Call DeepSeek V4 Flash to generate the design."""
    from anthropic import Anthropic

    key_path = Path("/tmp/.hdk")
    api_key = key_path.read_text().strip() if key_path.exists() else os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("No DeepSeek API key. Put it in /tmp/.hdk or ANTHROPIC_API_KEY env.")

    client = Anthropic(
        base_url="https://api.deepseek.com/anthropic",
        api_key=api_key)

    print("Calling DeepSeek V4 Flash...")
    t0 = time.time()

    resp = client.messages.create(
        model="deepseek-v4-flash",
        max_tokens=32768,
        system="你是城市设计AI。只输出JSON，不要输出markdown代码块或其他格式。所有GeoJSON坐标使用有效的经度/纬度数值。proposal.md使用中文Markdown。",
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "disabled"},
        timeout=600,
    )

    elapsed = time.time() - t0
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    print(f"Response: {len(text)} chars in {elapsed:.0f}s")

    # Parse JSON — try direct parse first, then try extracting from markdown
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try extracting from code fence
        import re
        match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        if match:
            return json.loads(match.group(1).strip())
        # Try finding first { ... }
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise


def write_submission(data: dict, submission: Path) -> None:
    """Write all generated files to the submission directory."""
    files = data.get("files", {})
    if not files:
        # Maybe DeepSeek returned a different structure
        print("Warning: no 'files' key in response. Raw keys:", list(data.keys())[:10])
        # Try alternate structure
        if isinstance(data, dict):
            files = {k: v for k, v in data.items() if isinstance(v, (str, dict))}

    written = 0
    for path, content in files.items():
        full_path = submission / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(content, (dict, list)):
            text = json.dumps(content, ensure_ascii=False, indent=2)
        else:
            text = str(content)

        full_path.write_text(text, encoding="utf-8")
        written += 1
        print(f"  ✓ {path} ({len(text)} chars)")

    print(f"\nWrote {written} files to {submission}")


def main():
    import argparse
    p = argparse.ArgumentParser(description="Generate urban design with DeepSeek")
    p.add_argument("submission", help="Target submission dir, e.g. submissions/test/ds-gen")
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip if submission dir already has files")
    args = p.parse_args()

    submission = (ROOT / args.submission).resolve()
    if args.skip_existing and submission.exists() and list(submission.glob("*")):
        print(f"Submission already exists at {submission}, skipping.")
        return

    submission.mkdir(parents=True, exist_ok=True)
    for d in ["geometry", "assets/figures", "report", "visual", "drawings"]:
        (submission / d).mkdir(parents=True, exist_ok=True)

    # Load facts
    print("Loading facts...")
    facts = load_facts()
    print(f"Facts: {len(facts)} chars")

    # Build prompt
    prompt = build_prompt(facts, str(args.submission))
    print(f"Prompt: {len(prompt)} chars")

    # Generate
    data = call_deepseek(prompt)

    # Write
    write_submission(data, submission)

    # Generate figures with urban-spatial-tooling
    print("\nGenerating figures...")
    from scripts.goal_driven_loop import _handle_generate_figure
    for ft in ["site_overview", "land_use", "key_areas", "mobility", "metrics"]:
        result = _handle_generate_figure(ft, [], str(args.submission))
        print(f"  {ft}: {result}")

    # Validate
    print("\nValidating CODE constraints...")
    from constraints.engine import ConstraintEngine
    engine = ConstraintEngine(ROOT)
    engine.load_registry()
    results = engine.validate(str(submission.relative_to(ROOT)))
    passed = sum(1 for r in results if r.outcome.name == "PASS")
    failed = [r for r in results if r.outcome.name == "FAIL"]
    print(f"CODE: {passed}/{len(results)} pass, {len(failed)} fail")
    for r in failed[:10]:
        print(f"  ❌ {r.constraint_id}: {r.detail[:100]}")

    print("\nDone! Run Gate 2 with:")
    print(f"  export HAIDIAN_JUDGE_BACKEND=deepseek && python3 scripts/panel_runner.py {args.submission}")


if __name__ == "__main__":
    main()
