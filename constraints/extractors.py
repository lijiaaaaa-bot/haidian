"""Extract hard constraints from physical repo data files.

Every constraint extracted here comes from a specific file in the repo.
The LLM never sees these constraints as prompts — they are enforced by CODE.

Usage:
    extractor = ConstraintExtractor(repo_root="/path/to/haidian")
    constraints = extractor.extract_all()
    # constraints is a list of dicts, each defining one hard rule
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class ConstraintExtractor:
    """Read repo data files and produce hard constraint definitions.

    Each constraint has:
      - constraint_id: unique kebab-case identifier
      - name: human-readable
      - source_file: which repo file it came from
      - source_field: which JSON field / section
      - check_type: "CODE" (deterministic) or "LLM" (needs semantic judgment)
      - check_function: name of the Python function that executes this check
      - params: parameters for the check function
      - severity: "critical" | "high" | "medium"
      - enabled: bool
      - category: "spatial" | "textual" | "metric" | "package" | "compliance"
    """

    def __init__(self, repo_root: str | Path = "."):
        self.root = Path(repo_root)
        self._cache: dict[str, Any] = {}

    def _read_json(self, relpath: str) -> dict:
        if relpath not in self._cache:
            path = self.root / relpath
            if path.exists():
                self._cache[relpath] = json.loads(path.read_text(encoding="utf-8"))
            else:
                self._cache[relpath] = {}
        return self._cache[relpath]

    def _read_text(self, relpath: str) -> str:
        key = f"__text__{relpath}"
        if key not in self._cache:
            path = self.root / relpath
            self._cache[key] = path.read_text(encoding="utf-8") if path.exists() else ""
        return self._cache[key]

    # ── Design Brief → spatial/area constraints ──────────────────────

    def extract_from_design_brief(self) -> list[dict]:
        """Extract area, coordinate, and scope constraints from design_brief.json."""
        brief = self._read_json("brief/site-package/design_brief.json")
        if not brief:
            return []

        constraints = []

        # Coordinate system
        coord = brief.get("coordinate_policy", {})
        constraints.append({
            "constraint_id": "C-COORD-001",
            "name": "area_calculation_crs",
            "description": "面积复算必须使用 EPSG:4548 投影坐标系",
            "source_file": "brief/site-package/design_brief.json",
            "source_field": "coordinate_policy.area_calculation_crs",
            "check_type": "CODE",
            "check_function": "verify_crs_used",
            "params": {
                "required_epsg": 4548,
                "check_metric_formulas": True,
            },
            "severity": "critical",
            "enabled": True,
            "category": "spatial",
        })

        # Area tolerances for each scope level
        scope_levels = brief.get("official_scope_levels", [])
        for scope in scope_levels:
            scope_id = scope["scope_id"]
            area_sqm = scope.get("area_sqm")
            if area_sqm:
                constraints.append({
                    "constraint_id": f"C-AREA-{scope_id}",
                    "name": f"area_tolerance_{scope_id}",
                    "description": f"{scope['label_zh']} 面积容差检查 (±5%)",
                    "source_file": "brief/site-package/design_brief.json",
                    "source_field": f"official_scope_levels.{scope_id}.area_sqm",
                    "check_type": "CODE",
                    "check_function": "verify_area_tolerance",
                    "params": {
                        "declared_area_sqm": area_sqm,
                        "tolerance_pct": 5.0,
                        "geometry_source": scope.get("provisional_geometry_path", ""),
                        "scope_label": scope["label_zh"],
                        "geometry_status": scope.get("geometry_status", ""),
                        # metrics.json key the engine cross-checks against the
                        # projected geometry (commit 8cf6409/0ef3638 pointed the
                        # hand-edited registry at real geometry via this key).
                        # Convention: the metric key is `{id}_sqm` when the id
                        # already ends in `_area`, else `{id}_area_sqm`.
                        "metric_key": (
                            f"{scope_id}_sqm"
                            if scope_id.endswith("_area")
                            else f"{scope_id}_area_sqm"
                        ),
                    },
                    "severity": "high",
                    "enabled": True,
                    "category": "spatial",
                })

        # Key area tolerances
        key_areas = brief.get("key_areas", [])
        for ka in key_areas:
            area_sqm = ka.get("area_sqm")
            if area_sqm:
                constraints.append({
                    "constraint_id": f"C-AREA-KEY-{ka['area_id']}",
                    "name": f"area_tolerance_{ka['area_id']}",
                    "description": f"{ka['label_zh']} 面积容差检查 (±5%)",
                    "source_file": "brief/site-package/design_brief.json",
                    "source_field": f"key_areas.{ka['area_id']}.area_sqm",
                    "check_type": "CODE",
                    "check_function": "verify_area_tolerance",
                    "params": {
                        "declared_area_sqm": area_sqm,
                        "tolerance_pct": 5.0,
                        "geometry_source": ka.get("provisional_geometry_path", ""),
                        "scope_label": ka["label_zh"],
                        "geometry_status": ka.get("geometry_status", ""),
                        "metric_key": (
                            f"{ka['area_id']}_sqm"
                            if ka["area_id"].endswith("_area")
                            else f"{ka['area_id']}_area_sqm"
                        ),
                    },
                    "severity": "high",
                    "enabled": True,
                    "category": "spatial",
                })

        return constraints

    # ── Allowed Design Space → layer constraints ─────────────────────

    def extract_from_allowed_design_space(self) -> list[dict]:
        """Extract layer requirements and forbidden claims from allowed_design_space.json."""
        ads = self._read_json("brief/site-package/allowed_design_space.json")
        if not ads:
            return []

        constraints = []

        # Required submission layers
        required_layers = ads.get("required_submission_layers", [])
        if required_layers:
            constraints.append({
                "constraint_id": "C-LAYER-001",
                "name": "required_layers_present",
                "description": "必交 GeoJSON 图层必须全部存在",
                "source_file": "brief/site-package/allowed_design_space.json",
                "source_field": "required_submission_layers",
                "check_type": "CODE",
                "check_function": "verify_required_layers",
                "params": {
                    "required_layers": required_layers,
                },
                "severity": "critical",
                "enabled": True,
                "category": "spatial",
            })

        # Locked layers (must not be modified)
        locked_layers = ads.get("locked_layers", [])
        if locked_layers:
            constraints.append({
                "constraint_id": "C-LAYER-002",
                "name": "locked_layers_untouched",
                "description": "锁定图层不得被修改",
                "source_file": "brief/site-package/allowed_design_space.json",
                "source_field": "locked_layers",
                "check_type": "CODE",
                "check_function": "verify_locked_layers",
                "params": {
                    "locked_layers": locked_layers,
                },
                "severity": "critical",
                "enabled": True,
                "category": "spatial",
            })

        # Editable layers
        editable_layers = ads.get("editable_layers", [])
        if editable_layers:
            constraints.append({
                "constraint_id": "C-LAYER-003",
                "name": "all_features_in_known_layers",
                "description": "所有 feature 的 layer 属性必须在已知图层列表中",
                "source_file": "brief/site-package/allowed_design_space.json",
                "source_field": "editable_layers + locked_layers",
                "check_type": "CODE",
                "check_function": "verify_layer_names",
                "params": {
                    "valid_layers": sorted(set(editable_layers + locked_layers)),
                },
                "severity": "high",
                "enabled": True,
                "category": "spatial",
            })

        # Geometry policy
        geo_policy = ads.get("geometry_policy", {})
        if geo_policy:
            constraints.append({
                "constraint_id": "C-GEO-001",
                "name": "features_within_boundary",
                "description": "所有生成 feature 必须在 site_boundary 内",
                "source_file": "brief/site-package/allowed_design_space.json",
                "source_field": "geometry_policy.generated_features_must_be_inside",
                "check_type": "CODE",
                "check_function": "verify_features_within_boundary",
                "params": {
                    "generated_layers": editable_layers,
                },
                "severity": "critical",
                "enabled": True,
                "category": "spatial",
            })

            constraints.append({
                "constraint_id": "C-GEO-002",
                "name": "no_gaps_in_land_use",
                "description": "land_use polygon 并集必须完全覆盖 site_boundary",
                "source_file": "brief/site-package/allowed_design_space.json",
                "source_field": "geometry_policy",
                "check_type": "CODE",
                "check_function": "verify_land_use_coverage",
                "params": {},
                "severity": "critical",
                "enabled": True,
                "category": "spatial",
            })

            constraints.append({
                "constraint_id": "C-GEO-003",
                "name": "no_land_use_overlap",
                "description": "相邻 land_use polygon 不得重叠",
                "source_file": "brief/site-package/allowed_design_space.json",
                "source_field": "geometry_policy",
                "check_type": "CODE",
                "check_function": "verify_no_land_use_overlap",
                "params": {},
                "severity": "critical",
                "enabled": True,
                "category": "spatial",
            })

        # Forbidden claims
        forbidden = ads.get("forbidden_claims", [])
        if forbidden:
            constraints.append({
                "constraint_id": "C-TEXT-FORBIDDEN",
                "name": "no_forbidden_claims",
                "description": "proposal.md 不得包含禁止性声明",
                "source_file": "brief/site-package/allowed_design_space.json",
                "source_field": "forbidden_claims",
                "check_type": "CODE",
                "check_function": "grep_forbidden_patterns",
                "params": {
                    "forbidden_patterns": forbidden,
                    "target_file": "proposal.md",
                },
                "severity": "critical",
                "enabled": True,
                "category": "compliance",
            })

        return constraints

    # ── Agent Taskbook → text requirements, forbidden claims ─────────

    def extract_from_taskbook(self) -> list[dict]:
        """Extract task coverage, boundary clause, and wording constraints."""
        tb = self._read_json("brief/site-package/agent_taskbook.json")
        if not tb:
            return []

        constraints = []

        # Required agent tasks
        agent_tasks = tb.get("required_agent_tasks", [])
        task_ids = []
        for t in agent_tasks:
            tid = t["requirement_id"]
            task_ids.append(tid)
            must_address = t.get("must_address_zh", [])
            forbidden = t.get("forbidden_claims_zh", [])

            # Each agent task becomes a coverage constraint
            constraints.append({
                "constraint_id": f"C-TASK-{tid.replace('.', '-')}",
                "name": f"task_coverage_{tid}",
                "description": f"compliance_matrix 必须覆盖 {t['title_zh']}",
                "source_file": "brief/site-package/agent_taskbook.json",
                "source_field": f"required_agent_tasks.{tid}",
                "check_type": "CODE",
                "check_function": "verify_task_coverage",
                "params": {
                    "requirement_id": tid,
                    "title_zh": t["title_zh"],
                    "must_address": must_address,
                    "forbidden_claims": forbidden,
                },
                "severity": "critical",
                "enabled": True,
                "category": "compliance",
            })

        # Boundary clause — forbidden final conclusions
        boundary = tb.get("boundary_clause", {})
        forbidden_conclusions = boundary.get("forbidden_final_conclusions_zh", [])
        if forbidden_conclusions:
            constraints.append({
                "constraint_id": "C-TEXT-BOUNDARY-001",
                "name": "no_forbidden_final_conclusions",
                "description": "proposal.md 不得出现 boundary_clause 禁止的法定结论",
                "source_file": "brief/site-package/agent_taskbook.json",
                "source_field": "boundary_clause.forbidden_final_conclusions_zh",
                "check_type": "CODE",
                "check_function": "grep_forbidden_patterns",
                "params": {
                    "forbidden_patterns": forbidden_conclusions,
                    "target_file": "proposal.md",
                },
                "severity": "critical",
                "enabled": True,
                "category": "compliance",
            })

        # Required wording
        required_wording = boundary.get("required_wording_zh", "")
        if required_wording:
            constraints.append({
                "constraint_id": "C-TEXT-BOUNDARY-002",
                "name": "required_wording_present",
                "description": "proposal.md 必须包含强制措辞",
                "source_file": "brief/site-package/agent_taskbook.json",
                "source_field": "boundary_clause.required_wording_zh",
                "check_type": "CODE",
                "check_function": "verify_required_wording",
                "params": {
                    "required_phrases": [
                        "概念建议",
                        "参考方案",
                        "可供专业团队深化研究",
                    ],
                    "target_file": "proposal.md",
                },
                "severity": "critical",
                "enabled": True,
                "category": "compliance",
            })

        # Co-creation charter
        charter = tb.get("co_creation_charter", [])
        for c in charter:
            constraints.append({
                "constraint_id": f"C-CHARTER-{c['principle_id'].replace('.', '-')}",
                "name": f"charter_{c['principle_id']}",
                "description": f"共创原则: {c['title_zh']} — {c['requirement_zh']}",
                "source_file": "brief/site-package/agent_taskbook.json",
                "source_field": f"co_creation_charter.{c['principle_id']}",
                "check_type": "LLM",
                "check_function": "llm_charter_check",
                "params": {
                    "principle_id": c["principle_id"],
                    "title_zh": c["title_zh"],
                    "requirement_zh": c["requirement_zh"],
                },
                "severity": "high",
                "enabled": True,
                "category": "compliance",
            })

        return constraints

    # ── Planning Limits → sanity bounds ────────────────────────────

    def extract_from_planning_limits(self) -> list[dict]:
        """Extract sanity bounds and missing-control documentation requirements."""
        limits = self._read_json("brief/site-package/ranges/planning_limits.json")
        if not limits:
            return []

        constraints = []

        # Sanity bounds
        bounds = limits.get("schema_sanity_bounds_not_planning_approval", {})
        for key, bound in bounds.items():
            if isinstance(bound, dict) and "min" in bound and "max" in bound:
                constraints.append({
                    "constraint_id": f"C-SANITY-{key}",
                    "name": f"sanity_bound_{key}",
                    "description": f"{key} 必须在合理范围内 [{bound['min']}, {bound['max']}]",
                    "source_file": "brief/site-package/ranges/planning_limits.json",
                    "source_field": f"schema_sanity_bounds_not_planning_approval.{key}",
                    "check_type": "CODE",
                    "check_function": "verify_sanity_bounds",
                    "params": {
                        "metric_key": key,
                        "min_val": bound["min"],
                        "max_val": bound.get("max"),
                    },
                    "severity": "high",
                    "enabled": True,
                    "category": "metric",
                })

        # Missing controls → must be documented in assumptions
        controls = limits.get("official_planning_controls", {})
        missing_controls = [
            k for k, v in controls.items()
            if isinstance(v, dict) and v.get("status") == "missing"
        ]
        if missing_controls:
            constraints.append({
                "constraint_id": "C-ASSUMPTIONS-001",
                "name": "missing_controls_documented",
                "description": "缺失的控规条件必须在 assumptions.json 中记录",
                "source_file": "brief/site-package/ranges/planning_limits.json",
                "source_field": "official_planning_controls",
                "check_type": "CODE",
                "check_function": "verify_missing_controls_documented",
                "params": {
                    "missing_controls": missing_controls,
                },
                "severity": "high",
                "enabled": True,
                "category": "compliance",
            })

        return constraints

    # ── Source Registry → data authority constraints ─────────────────

    def extract_from_source_registry(self) -> list[dict]:
        """Extract source usage rules from data/source_registry.json."""
        sr = self._read_json("data/source_registry.json")
        if not sr:
            return []

        constraints = []

        sources = sr.get("sources", [])
        provisional_sources = [
            s for s in sources
            if s.get("usable_for_formal") == "provisional_only"
        ]
        needs_review_sources = [
            s for s in sources
            if s.get("usable_for_formal") == "needs_review"
        ]

        if provisional_sources:
            constraints.append({
                "constraint_id": "C-SOURCE-001",
                "name": "no_provisional_source_upgrade",
                "description": "provisional_only 来源不得被当作 formal 依据使用",
                "source_file": "data/source_registry.json",
                "source_field": "sources[*].usable_for_formal",
                "check_type": "CODE",
                "check_function": "verify_source_authority",
                "params": {
                    "provisional_source_ids": [s["source_id"] for s in provisional_sources],
                    "formal_required_fields": ["official_boundary", "statutory_control", "engineering_conclusion"],
                },
                "severity": "critical",
                "enabled": True,
                "category": "compliance",
            })

        return constraints

    # ── Enums → valid value constraints ──────────────────────────────

    # Known keys in enum JSON files that contain the actual enum array
    _ENUM_ARRAY_KEYS = ("codes", "types", "classes", "layers")

    def _extract_codes_from_enum_data(self, data) -> list[str]:
        """Extract actual enum codes from various enum file structures.

        Handles:
          - Top-level list: [{"code": "01", ...}, ...]
          - Dict with known array keys: {"codes": [{"code": "07", ...}], ...}
          - Dict with unknown keys: tries known array keys, falls back to dict keys
        """
        if isinstance(data, list):
            return [item.get("code", "") for item in data if isinstance(item, dict)]

        if isinstance(data, dict):
            # Try each known array key
            for key in self._ENUM_ARRAY_KEYS:
                if key in data and isinstance(data[key], list):
                    return [
                        item.get("code", "")
                        for item in data[key]
                        if isinstance(item, dict)
                    ]
            # Fallback: if no known array key found, return dict keys
            # (this is the old buggy behavior, preserved as last resort)
            return list(data.keys())

        return []

    def extract_from_enums(self) -> list[dict]:
        """Extract enum validation constraints."""
        enum_files = {
            "land_use_codes": "brief/site-package/enums/land_use_codes.json",
            "building_types": "brief/site-package/enums/building_types.json",
            "road_classes": "brief/site-package/enums/road_classes.json",
        }

        constraints = []
        for enum_name, path in enum_files.items():
            data = self._read_json(path)
            if not data:
                continue
            codes = self._extract_codes_from_enum_data(data)

            if codes:
                constraints.append({
                    "constraint_id": f"C-ENUM-{enum_name}",
                    "name": f"valid_{enum_name}",
                    "description": f"{enum_name} 值必须在合法枚举范围内",
                    "source_file": path,
                    "source_field": "enum values",
                    "check_type": "CODE",
                    "check_function": "verify_enum_values",
                    "params": {
                        "enum_name": enum_name,
                        "valid_codes": codes,
                        "target_geojson_field": enum_name.replace("_codes", "_code"),
                    },
                    "severity": "high",
                    "enabled": True,
                    "category": "spatial",
                })

        return constraints

    # ── Provisional Boundaries → coordinate range constraints ───────

    def extract_from_boundaries(self) -> list[dict]:
        """Extract spatial extent constraints from provisional boundaries."""
        geo = self._read_json("brief/site-package/geometry/provisional_boundaries.geojson")
        if not geo or "features" not in geo:
            return []

        constraints = []
        for feat in geo["features"]:
            props = feat.get("properties", {})
            feat_id = props.get("id", "unknown")
            layer = props.get("layer", "")
            scope_id = props.get("scope_id", "")

            if layer == "SITE_BOUNDARY" and props.get("official_boundary") == False:
                constraints.append({
                    "constraint_id": f"C-BOUNDARY-PROV-{feat_id}",
                    "name": f"provisional_boundary_marked_{feat_id}",
                    "description": f"提交的 site_boundary 如使用 {props.get('name_zh', feat_id)} 必须标记为 provisional_constraint",
                    "source_file": "brief/site-package/geometry/provisional_boundaries.geojson",
                    "source_field": f"features.{feat_id}",
                    "check_type": "CODE",
                    "check_function": "verify_provisional_marking",
                    "params": {
                        "geometry_role": "provisional_constraint",
                        "official_boundary": False,
                        "boundary_precision_required": True,
                        "usage_note_required": True,
                    },
                    "severity": "critical",
                    "enabled": True,
                    "category": "spatial",
                })

        return constraints

    # ── Master extractor ─────────────────────────────────────────────

    def extract_all(self) -> list[dict]:
        """Extract all constraints from all repo data sources."""
        all_constraints = []
        extractors = [
            self.extract_from_design_brief,
            self.extract_from_allowed_design_space,
            self.extract_from_taskbook,
            self.extract_from_planning_limits,
            self.extract_from_source_registry,
            self.extract_from_enums,
            self.extract_from_boundaries,
        ]
        for extractor in extractors:
            try:
                all_constraints.extend(extractor())
            except Exception as e:
                print(f"Warning: extractor {extractor.__name__} failed: {e}")

        return all_constraints

    def generate_registry(self, output_path: Path | None = None) -> dict:
        """Generate the full constraint registry JSON and optionally write to file."""
        constraints = self.extract_all()
        # C-SM state-machine entries are code-defined (not derived from data
        # files), so they live in state_machine_checks, not extract_all. Merge
        # them here to keep regeneration idempotent against the committed
        # registry (1af177d had hand-appended them to registry.json, which a
        # naive regen would drop).
        from constraints.state_machine_checks import STATE_MACHINE_REGISTRY_ENTRIES

        constraints.extend(STATE_MACHINE_REGISTRY_ENTRIES)
        registry = {
            "schema_version": "1.0",
            "generated_from": "repo physical data files",
            "generation_note": "此文件由 constraints/extractors.py 从 repo 数据文件自动生成；C-SM* 条目来自 constraints/state_machine_checks.py 的代码定义。手动添加的约束应在 manual_overrides 中。",
            "total_constraints": len(constraints),
            "constraints": constraints,
            "manual_overrides": [],
        }
        if output_path:
            output_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return registry
