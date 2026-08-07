"""Urban Design Domain Model — the professional abstraction.

Before we can write constraints or call LLMs, we must model WHAT urban design is.
This module defines the core domain types that the state machine operates on.

Every type has:
  - A clear professional definition (which Chinese planning standard it comes from)
  - Validation rules (hard constraints)
  - Relationship to other types (the spatial hierarchy)
  - LLM judgment points (where creative decisions happen within constraints)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ═══════════════════════════════════════════════════════════════════════
# Foundation: Spatial Reference System
# Source: design_brief.json → coordinate_policy
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CoordinateSystem:
    """The spatial reference for all geometry.

    HARD CONSTRAINT: All area calculations MUST use EPSG:4548.
    Source: brief/site-package/design_brief.json → coordinate_policy
    """
    exchange_epsg: int = 4326   # GeoJSON storage
    calculation_epsg: int = 4548  # Area/metric calculation (CGCS2000 3-degree Gauss-Kruger CM 117E)
    unit_length: str = "m"
    unit_area: str = "sqm"

    def validate(self) -> bool:
        return self.calculation_epsg == 4548 and self.exchange_epsg == 4326


# ═══════════════════════════════════════════════════════════════════════
# Spatial Hierarchy: Three-Level Scope System
# Source: design_brief.json → official_scope_levels + key_areas
# Chinese planning standard: 总体规划→分区规划→详细规划
# ═══════════════════════════════════════════════════════════════════════

class ScopeLevel(Enum):
    """The three-tier planning hierarchy mandated by the official announcement."""
    COORDINATED_RESEARCH = "coordinated_research_area"    # 统筹研究范围 43.6 km²
    OVERALL_DESIGN = "overall_design_area"                 # 总体设计范围 11.4 km²
    KEY_DETAILED = "key_detailed_design_area"              # 重点区域范围 368.4 ha


@dataclass(frozen=True)
class ScopeDefinition:
    """One level in the spatial hierarchy.

    HARD CONSTRAINT: area_sqm is the OFFICIAL value from the government announcement.
    Generator MUST NOT fabricate a different number.
    """
    scope_id: str
    label_zh: str
    area_sqm: float                 # Official declared area — hard constraint
    boundary_text_zh: str           # Official text description of boundary
    geometry_status: str            # "exact_polygon_missing_provisional_available"

    @property
    def area_km2(self) -> float:
        return self.area_sqm / 1_000_000

    @property
    def area_ha(self) -> float:
        return self.area_sqm / 10_000


@dataclass(frozen=True)
class KeyAreaDefinition:
    """One of the three key detailed design areas.

    HARD CONSTRAINT: Three areas must not overlap and must be within the overall design area.
    Source: design_brief.json → key_areas
    """
    area_id: str
    label_zh: str
    area_sqm: float                 # Official declared area
    area_ha: float
    role_zh: str                    # From agent_taskbook: three_areas_two_wings

    def validate_area(self, submitted_area: float, tolerance_pct: float = 5.0) -> bool:
        """HARD: submitted area must be within tolerance of official value."""
        return abs(submitted_area - self.area_sqm) / self.area_sqm * 100 <= tolerance_pct


# ═══════════════════════════════════════════════════════════════════════
# GeoJSON Layer Types — the spatial data model
# Source: allowed_design_space.json → editable_layers + locked_layers
# Each layer has a professional definition from Chinese planning standards
# ═══════════════════════════════════════════════════════════════════════

class LayerRole(Enum):
    """What role a GeoJSON layer plays in the submission."""
    CONSTRAINT = "constraint"    # Locked: SITE_BOUNDARY, HERITAGE, EXISTING_WATER, etc.
    DESIGN = "design"            # Editable: LAND_USE, BUILDINGS, ROADS, GREEN_SPACE, etc.


@dataclass(frozen=True)
class LayerDefinition:
    """A GeoJSON layer with its professional definition.

    HARD CONSTRAINT: locked layers MUST NOT be modified by the Generator.
    HARD CONSTRAINT: required layers MUST all be present in the submission.
    """
    layer_id: str
    label_zh: str
    role: LayerRole
    geometry_type: str  # Polygon, LineString, Point, MultiPolygon
    description: str = ""
    required_attributes: tuple[str, ...] = ("id", "layer", "source_type", "confidence", "geometry_role")

    @property
    def is_locked(self) -> bool:
        return self.role == LayerRole.CONSTRAINT

    @property
    def is_editable(self) -> bool:
        return self.role == LayerRole.DESIGN

    @property
    def filename(self) -> str:
        return f"{self.layer_id.lower()}.geojson"


# ═══════════════════════════════════════════════════════════════════════
# Land Use Classification
# Source: MNR Land Use Classification Guide (自然资源部 2023)
# HARD CONSTRAINT: all land_use_code values must be from this enum
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LandUseCode:
    """One valid land use code from the national classification standard."""
    code: str
    name_zh: str
    category: str  # "residential", "commercial", "industrial", "public", "green", "transport", etc.

    def __str__(self) -> str:
        return f"{self.code} ({self.name_zh})"


# ═══════════════════════════════════════════════════════════════════════
# Design Constraints — professional planning limits
# Source: ranges/planning_limits.json + Chinese planning standards
# These are HARD bounds that the LLM's creative decisions must stay within
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PlanningLimit:
    """A professional planning limit — a hard numeric bound.

    HARD CONSTRAINT: Generator output MUST respect these bounds.
    If the official control value is "missing", the Generator MUST document
    the gap in assumptions.json, NOT fabricate a value.
    """
    control_id: str
    label_zh: str
    min_val: float | None = None
    max_val: float | None = None
    status: str = "missing"  # "available" | "missing"
    needed_from: str = ""    # Which official document provides this

    def is_satisfied_by(self, value: float) -> bool:
        """HARD: check if a value respects this limit."""
        if self.min_val is not None and value < self.min_val:
            return False
        if self.max_val is not None and value > self.max_val:
            return False
        return True

    @property
    def is_available(self) -> bool:
        return self.status == "available"

    @property
    def must_document_gap(self) -> bool:
        """If the official value is missing, the gap MUST be documented."""
        return self.status == "missing"


# ═══════════════════════════════════════════════════════════════════════
# Professional Standards — the rules that govern design
# Source: brief/site-package/standards/standards.json
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ProfessionalStandard:
    """A mandatory professional standard that the design must respond to.

    Each standard has specific requirements that the design must address.
    The standard_matrix.json documents HOW the design responds.
    """
    standard_id: str
    name_zh: str
    publisher: str
    description: str = ""
    local_reference_path: str = ""  # Path to local snapshot in standards/references/


# ═══════════════════════════════════════════════════════════════════════
# Boundary Clause — what LLM CANNOT say
# Source: agent_taskbook.json → boundary_clause
# This is the core "hard law" that separates concept from statutory claim
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BoundaryClause:
    """The hard boundary between conceptual suggestion and statutory planning.

    This is THE most important constraint in the entire system.
    Violating it → submission is legally invalid.

    HARD CONSTRAINT (CODE, not LLM):
      - proposal.md MUST NOT contain forbidden_final_conclusions
      - proposal.md MUST contain required_wording

    LLM JUDGMENT POINT:
      - Is the tone consistently suggestive, not declarative?
    """
    scope_zh: str
    must_state_zh: str
    forbidden_final_conclusions: tuple[str, ...] = field(default_factory=tuple)
    required_wording: str = ""

    def contains_forbidden(self, text: str) -> list[str]:
        """CODE check: find any forbidden conclusions in text."""
        hits = []
        for phrase in self.forbidden_final_conclusions:
            if phrase in text:
                hits.append(phrase)
        return hits

    def contains_required_wording(self, text: str) -> bool:
        """CODE check: verify required wording is present."""
        return self.required_wording in text


# ═══════════════════════════════════════════════════════════════════════
# Agent Tasks — the 6 required design tasks
# Source: agent_taskbook.json → required_agent_tasks
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AgentTask:
    """One of the 6 mandatory agent tasks.

    Each task has:
      - must_address: what the proposal MUST cover (CODE checkable)
      - required_outputs: what files/artifacts must exist (CODE checkable)
      - forbidden_claims: what the proposal MUST NOT say (CODE checkable)
      - JUDGMENT: is the design response actually GOOD? (LLM only)
    """
    requirement_id: str        # agent.1 ~ agent.6
    title_zh: str
    must_address: tuple[str, ...] = field(default_factory=tuple)
    required_outputs: tuple[str, ...] = field(default_factory=tuple)
    forbidden_claims: tuple[str, ...] = field(default_factory=tuple)


# ═══════════════════════════════════════════════════════════════════════
# Submission Package — what the Generator must produce
# Source: SKILL.md → Output Package
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RequiredFile:
    """One required file in the submission package."""
    path: str           # Relative to submissions/<login>/<slug>/
    description: str
    file_type: str      # "markdown", "geojson", "json", "png", "pdf", "html"
    required: bool = True

    @property
    def extension(self) -> str:
        return self.path.rsplit(".", 1)[-1] if "." in self.path else ""


# ═══════════════════════════════════════════════════════════════════════
# The Complete Domain Model — assembled from repo data
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class UrbanDesignDomain:
    """The complete urban design domain model for the haidian project.

    This is assembled from the repo's physical data files.
    It defines WHAT urban design IS in this project — the professional
    concepts, constraints, and standards that the state machine operates on.
    """

    coordinate_system: CoordinateSystem = field(default_factory=CoordinateSystem)
    scope_levels: list[ScopeDefinition] = field(default_factory=list)
    key_areas: list[KeyAreaDefinition] = field(default_factory=list)
    layers: list[LayerDefinition] = field(default_factory=list)
    planning_limits: list[PlanningLimit] = field(default_factory=list)
    professional_standards: list[ProfessionalStandard] = field(default_factory=list)
    boundary_clause: BoundaryClause | None = None
    agent_tasks: list[AgentTask] = field(default_factory=list)
    required_files: list[RequiredFile] = field(default_factory=list)
    land_use_codes: list[LandUseCode] = field(default_factory=list)

    # Three positionings + five functions (from agent_taskbook)
    positionings: list[str] = field(default_factory=list)
    five_functions: list[str] = field(default_factory=list)

    @classmethod
    def from_repo(cls, repo_root: str | None = None) -> "UrbanDesignDomain":
        """Build the domain model from the repo's physical data files.

        This is the single source of truth for all professional concepts.
        """
        import json
        from pathlib import Path

        root = Path(repo_root) if repo_root else Path(".")

        def read_json(path: str) -> dict:
            f = root / path
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

        # ── Coordinate System ──
        brief = read_json("brief/site-package/design_brief.json")
        coord = brief.get("coordinate_policy", {})
        crs = CoordinateSystem(
            exchange_epsg=int(coord.get("geojson_exchange_crs", "EPSG:4326").split(":")[-1]),
            calculation_epsg=int(coord.get("area_calculation_crs", "EPSG:4548").split(":")[-1]),
        )

        # ── Scope Levels ──
        scope_levels = []
        for s in brief.get("official_scope_levels", []):
            scope_levels.append(ScopeDefinition(
                scope_id=s["scope_id"],
                label_zh=s["label_zh"],
                area_sqm=s["area_sqm"],
                boundary_text_zh=s.get("boundary_text_zh", ""),
                geometry_status=s.get("geometry_status", ""),
            ))

        # ── Key Areas ──
        key_areas = []
        for ka in brief.get("key_areas", []):
            key_areas.append(KeyAreaDefinition(
                area_id=ka["area_id"],
                label_zh=ka["label_zh"],
                area_sqm=ka["area_sqm"],
                area_ha=ka.get("area_ha", ka["area_sqm"] / 10000),
                role_zh=ka.get("role_zh", ""),
            ))

        # ── Layers ──
        ads = read_json("brief/site-package/allowed_design_space.json")
        layers = []
        for layer_id in ads.get("editable_layers", []):
            layers.append(LayerDefinition(
                layer_id=layer_id, label_zh=layer_id,
                role=LayerRole.DESIGN, geometry_type="Polygon",
            ))
        for layer_id in ads.get("locked_layers", []):
            layers.append(LayerDefinition(
                layer_id=layer_id, label_zh=layer_id,
                role=LayerRole.CONSTRAINT, geometry_type="Polygon",
            ))

        # ── Planning Limits ──
        limits_data = read_json("brief/site-package/ranges/planning_limits.json")
        planning_limits = []
        for cid, cdata in limits_data.get("official_planning_controls", {}).items():
            if isinstance(cdata, dict):
                planning_limits.append(PlanningLimit(
                    control_id=cid,
                    label_zh=cid,
                    status=cdata.get("status", "missing"),
                    needed_from=cdata.get("needed_from", ""),
                ))
        # Sanity bounds
        for key, bound in limits_data.get("schema_sanity_bounds_not_planning_approval", {}).items():
            if isinstance(bound, dict):
                planning_limits.append(PlanningLimit(
                    control_id=key,
                    label_zh=key,
                    min_val=bound.get("min"),
                    max_val=bound.get("max"),
                    status="available",
                ))

        # ── Professional Standards ──
        standards_data = read_json("brief/site-package/standards/standards.json")
        professional_standards = []
        for std in standards_data.get("standards", []):
            professional_standards.append(ProfessionalStandard(
                standard_id=std.get("standard_id", ""),
                name_zh=std.get("name_zh", ""),
                publisher=std.get("publisher", ""),
                local_reference_path=std.get("local_reference_path", ""),
            ))

        # ── Boundary Clause ──
        tb = read_json("brief/site-package/agent_taskbook.json")
        bc = tb.get("boundary_clause", {})
        boundary_clause = BoundaryClause(
            scope_zh=bc.get("scope_zh", ""),
            must_state_zh=bc.get("must_state_zh", ""),
            forbidden_final_conclusions=tuple(bc.get("forbidden_final_conclusions_zh", [])),
            required_wording=bc.get("required_wording_zh", ""),
        )

        # ── Agent Tasks ──
        agent_tasks = []
        for t in tb.get("required_agent_tasks", []):
            agent_tasks.append(AgentTask(
                requirement_id=t["requirement_id"],
                title_zh=t["title_zh"],
                must_address=tuple(t.get("must_address_zh", [])),
                required_outputs=tuple(t.get("required_outputs", [])),
                forbidden_claims=tuple(t.get("forbidden_claims_zh", [])),
            ))

        # ── Required Files ──
        required_files = [
            RequiredFile("proposal.md", "主体方案文本", "markdown"),
            RequiredFile("manifest.json", "包元数据", "json"),
            RequiredFile("agent.json", "Agent 身份", "json"),
            RequiredFile("metrics.json", "指标体系", "json"),
            RequiredFile("assumptions.json", "假设与缺口", "json"),
            RequiredFile("sources.json", "资料来源", "json"),
            RequiredFile("self_check.json", "自检结果", "json"),
            RequiredFile("compliance_matrix.json", "任务响应表", "json"),
            RequiredFile("standard_matrix.json", "标准响应表", "json"),
            RequiredFile("design_depth_matrix.json", "设计深度证据", "json"),
            RequiredFile("geometry/site_boundary.geojson", "设计边界", "geojson"),
            RequiredFile("geometry/key_areas.geojson", "重点区域", "geojson"),
            RequiredFile("geometry/land_use.geojson", "用地布局", "geojson"),
            RequiredFile("geometry/buildings.geojson", "建筑", "geojson"),
            RequiredFile("geometry/roads.geojson", "道路", "geojson"),
            RequiredFile("geometry/green_space.geojson", "绿地", "geojson"),
            RequiredFile("geometry/public_space.geojson", "公共空间", "geojson"),
            RequiredFile("geometry/constraints.geojson", "约束条件", "geojson"),
            RequiredFile("geometry/phasing.geojson", "分期实施", "geojson"),
            RequiredFile("assets/figures/site-overview.png", "总体概念图", "png"),
            RequiredFile("assets/figures/land-use-structure.png", "空间结构图", "png"),
            RequiredFile("assets/figures/key-areas.png", "重点区索引图", "png"),
            RequiredFile("assets/figures/mobility-bluegreen.png", "交通蓝绿系统图", "png"),
            RequiredFile("assets/figures/metrics-evidence.png", "指标证据链图", "png"),
            RequiredFile("report/proposal.html", "离线阅读版", "html"),
            RequiredFile("report/copyright_statement.md", "版权声明", "markdown"),
            RequiredFile("drawings/a3-booklet.pdf", "A3 文册", "pdf"),
            RequiredFile("drawings/a0-boards.pdf", "A0 展板", "pdf"),
            RequiredFile("visual/index.html", "离线展示页", "html"),
        ]

        # ── Positionings + Functions ──
        positionings = tb.get("positioning_zh", [])
        five_functions = tb.get("five_functions_zh", [])

        # ── Land Use Codes ──
        lu_data = read_json("brief/site-package/enums/land_use_codes.json")
        land_use_codes = []
        if isinstance(lu_data, list):
            for item in lu_data:
                if isinstance(item, dict):
                    land_use_codes.append(LandUseCode(
                        code=item.get("code", ""),
                        name_zh=item.get("name_zh", ""),
                        category=item.get("category", ""),
                    ))

        return cls(
            coordinate_system=crs,
            scope_levels=scope_levels,
            key_areas=key_areas,
            layers=layers,
            planning_limits=planning_limits,
            professional_standards=professional_standards,
            boundary_clause=boundary_clause,
            agent_tasks=agent_tasks,
            required_files=required_files,
            land_use_codes=land_use_codes,
            positionings=positionings,
            five_functions=five_functions,
        )
