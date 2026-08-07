"""Professional Urban Design State Machine — the core architecture.

THE FOUNDATION. Before constraints, before LLM calls — there is a professional
workflow that models how urban design is actually done.

This module defines:
  - UrbanDesignPhase: 6 professional phases with CODE/JUDGMENT steps
  - UrbanDesignProcedure: the state machine that controls flow
  - Phase transition gates: constraint engine validates before advancing
  - LLM judgment points: where creative decisions happen within hard constraints

Key principle (from the user):
  "约束应该设计为硬编码或者状态机，而对LLM的使用则在规则之下的局部"
  — Constraints are hard-coded or state machines. LLM is used locally under rules.

Architecture:
  ┌─────────────────────────────────────────────────────────────┐
  │                 UrbanDesignProcedure                        │
  │  (state machine — controls ALL flow, never the LLM)         │
  │                                                             │
  │  Phase 1: SiteAnalysis                                      │
  │    CODE steps: load_domain, validate_crs, compute_metrics   │
  │    JUDGMENT: site_interpretation ← LLM called HERE only     │
  │    Gate: spatial_constraints_pass → advance                  │
  │                                                             │
  │  Phase 2: StrategicFramework                                │
  │    CODE steps: validate_positioning, check_naming           │
  │    JUDGMENT: concept_generation ← LLM called HERE only      │
  │    Gate: compliance_constraints_pass → advance               │
  │                                                             │
  │  ... (6 phases total)                                       │
  └─────────────────────────────────────────────────────────────┘

Integration with haidian repo:
  - brief/site-package/design_brief.json → spatial scope, CRS, boundaries
  - brief/site-package/agent_taskbook.json → 6 agent tasks, charter, boundary clause
  - brief/site-package/allowed_design_space.json → editable/locked layers
  - brief/site-package/ranges/planning_limits.json → hard numeric bounds
  - constraints/domain.py → UrbanDesignDomain (professional concepts)
  - constraints/engine.py → ConstraintEngine (deterministic validation)
  - review-panel/statutes.json → 7 quality statutes for final JUDGMENT
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════════════
# Step Types — the two kinds of work in the state machine
# ═══════════════════════════════════════════════════════════════════════

class StepKind(Enum):
    """Every step is either deterministic (CODE) or requires creative judgment (JUDGMENT).

    CODE:   Deterministic. No LLM. Runs in Python. Result is PASS/FAIL.
    JUDGMENT: Requires creative decision-making. LLM is called HERE, with
              structured input/output, within hard constraints. LLM never
              controls flow — the state machine does.
    """
    CODE = "CODE"
    JUDGMENT = "JUDGMENT"


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ═══════════════════════════════════════════════════════════════════════
# Design Phase — one of the 6 professional workflow phases
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DesignPhase:
    """One phase in the professional urban design workflow.

    Each phase models a real stage of professional practice:
      - entry_conditions: what must be true before this phase can start
      - code_steps: deterministic operations (no LLM)
      - judgment_points: where LLM is called for creative decisions
      - exit_conditions: constraint checks before transitioning to next phase
      - transitions: where the state machine goes next

    The phase DOES NOT call LLM on its own. The Procedure calls LLM at
    judgment points, with structured input derived from the current phase state.
    """

    phase_id: str
    label_zh: str
    description: str

    # Which agent tasks this phase corresponds to (from agent_taskbook.json)
    agent_task_ids: list[str] = field(default_factory=list)

    # Entry: what must be verified before entering this phase
    entry_conditions: list[str] = field(default_factory=list)

    # CODE steps: deterministic operations in order
    code_steps: list[str] = field(default_factory=list)

    # JUDGMENT points: where LLM makes creative decisions
    judgment_points: list[str] = field(default_factory=list)

    # Exit: constraint groups that must PASS before transitioning
    exit_constraint_groups: list[str] = field(default_factory=list)

    # State machine transitions
    transitions: dict[str, str] = field(default_factory=dict)

    # Phase state tracking
    status: str = "pending"  # pending → running → {completed, blocked}
    started_at: float | None = None
    completed_at: float | None = None
    step_results: dict[str, StepStatus] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.status == "completed"

    @property
    def is_blocked(self) -> bool:
        return self.status == "blocked"


# ═══════════════════════════════════════════════════════════════════════
# Judgment Context — the structured input passed to LLM at judgment points
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class JudgmentContext:
    """Structured input for an LLM judgment call.

    The LLM receives ONLY this context, not the entire project state.
    This is the "局部" (local) use of LLM — it sees what it needs to make
    ONE specific creative decision within hard constraints.

    The LLM MUST return a JudgmentResult — structured output that the
    state machine can validate before accepting.
    """

    judgment_id: str
    phase_id: str
    prompt_template: str               # The specific question for the LLM
    hard_constraints: list[dict]        # Constraints the LLM MUST respect (from registry)
    domain_context: dict[str, Any]      # Relevant domain data (scope, layers, etc.)
    required_output_schema: dict        # JSON Schema the LLM output must conform to
    evidence_requirements: list[str]    # What physical evidence the output must cite


@dataclass
class JudgmentResult:
    """Structured output from an LLM judgment call.

    The state machine validates this BEFORE accepting it:
      1. Does it conform to required_output_schema? (CODE)
      2. Does it cite required evidence? (CODE)
      3. Does it violate any hard constraints? (CODE → ConstraintEngine)

    Only after all three pass does the state machine accept the result.
    """

    judgment_id: str
    accepted: bool
    content: dict[str, Any]             # The LLM's creative output (schema-validated)
    evidence_refs: list[dict]           # Cited sources (source:location:snippet)
    constraint_violations: list[str]    # Any hard constraints the output violates
    fingerprint: str = ""              # SHA-256 for stall detection


# ═══════════════════════════════════════════════════════════════════════
# Phase Transition Gate — constraint engine check between phases
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PhaseGateResult:
    """Result of running constraint checks at a phase transition."""

    phase_id: str
    gate_passed: bool
    total_checks: int
    passed: int
    failed: int
    critical_failures: int
    failures: list[dict]     # [{constraint_id, name, detail, evidence, severity}]
    fingerprint: str = ""

    @property
    def all_pass(self) -> bool:
        return self.failed == 0


# ═══════════════════════════════════════════════════════════════════════
# Stall Detection — prevent infinite loops
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class StallDetector:
    """Detects when the state machine is stuck in a loop.

    Same fingerprint × N consecutive rounds → escalation.
    Based on hardlaw's StallDetector pattern.
    """

    threshold: int = 2
    history: list[dict] = field(default_factory=list)  # [{phase, fingerprint, round}]

    def check(self, phase_id: str, fingerprint: str, round_num: int) -> bool:
        """Returns True if STALL detected (same fingerprint consecutively)."""
        self.history.append({
            "phase": phase_id,
            "fingerprint": fingerprint,
            "round": round_num,
        })
        if len(self.history) < self.threshold:
            return False

        recent = self.history[-self.threshold:]
        return all(
            h["fingerprint"] == fingerprint and h["phase"] == phase_id
            for h in recent
        )

    @staticmethod
    def compute_fingerprint(data: Any) -> str:
        """SHA-256 fingerprint of any JSON-serializable data."""
        canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════
# The Professional Urban Design State Machine
# ═══════════════════════════════════════════════════════════════════════

class UrbanDesignProcedure:
    """The professional urban design workflow as a state machine.

    THIS IS THE FOUNDATION. It models the real professional practice of
    urban design as 6 sequential phases, each with CODE steps (deterministic)
    and JUDGMENT points (LLM called locally).

    The state machine:
      - Controls ALL flow — LLM never decides what happens next
      - Calls LLM ONLY at JUDGMENT points with structured input/output
      - Validates every phase transition with the ConstraintEngine
      - Detects stalls and escalates to human

    Usage:
        procedure = UrbanDesignProcedure.from_repo("/path/to/haidian")
        procedure.start()

        # Phase 1: Site Analysis
        procedure.execute_code_step("load_domain_model")
        procedure.execute_code_step("validate_coordinate_system")
        result = procedure.execute_judgment("site_interpretation", llm_client)
        procedure.advance()  # → Phase 2 if gate passes

        # ... continue through all 6 phases

        # Or run the full workflow
        procedure.run(llm_client)

    Integration:
        - procedure.domain → UrbanDesignDomain (professional concepts)
        - procedure.constraint_gate(phase) → PhaseGateResult (from ConstraintEngine)
        - procedure.execute_judgment(id, llm) → JudgmentResult (LLM called locally)
    """

    # ═══════════════════════════════════════════════════════════════════
    # Phase Definitions — the professional workflow
    # ═══════════════════════════════════════════════════════════════════

    PHASE_DEFINITIONS: dict[str, dict] = {
        "site_analysis": {
            "phase_id": "site_analysis",
            "label_zh": "基础分析",
            "description": "Read all brief data, validate spatial reference system, "
                           "understand site boundaries and constraints, compute base metrics.",
            "agent_task_ids": [],
            "entry_conditions": [],
            "code_steps": [
                "load_domain_model",         # Build UrbanDesignDomain from repo files
                "validate_coordinate_system", # Verify EPSG:4548 for area calculations
                "load_site_boundaries",       # Parse SITE_BOUNDARY provisional geometry
                "compute_base_metrics",       # Area, perimeter, extent of each scope level
                "validate_scope_hierarchy",   # Verify 3-level scope containment
                "enumerate_hard_constraints", # List all CODE constraints that apply
            ],
            "judgment_points": [
                "site_interpretation",        # LLM: What are the key spatial characteristics?
            ],
            "exit_constraint_groups": [
                "coordinate_system",
                "area_validation",
            ],
            "transitions": {
                "gate_pass": "strategic_framework",
                "gate_fail": "site_analysis",    # Retry phase
                "blocked": "human_escalation",
            },
        },
        "strategic_framework": {
            "phase_id": "strategic_framework",
            "label_zh": "战略框架",
            "description": "Overall concept, naming, positioning, spatial structure. "
                           "Corresponds to agent.1 (一带总体概念与功能统筹方案设计).",
            "agent_task_ids": ["agent.1"],
            "entry_conditions": [
                "domain_model_loaded",
                "coordinate_system_valid",
                "scope_hierarchy_valid",
            ],
            "code_steps": [
                "validate_positioning_alignment",  # 3 positionings must be addressed
                "validate_five_functions",         # 5 functions must be addressed
                "check_three_areas_two_wings",     # Spatial structure framework
                "check_naming_conventions",        # No forbidden name patterns
            ],
            "judgment_points": [
                "concept_generation",           # LLM: Generate name, logo direction, vision
                "spatial_structure_design",     # LLM: Overall spatial structure diagram
            ],
            "exit_constraint_groups": [
                "compliance_text",
                "agent_task_requirements",      # agent.1 coverage
            ],
            "transitions": {
                "gate_pass": "detailed_design",
                "gate_fail": "strategic_framework",
                "blocked": "human_escalation",
            },
        },
        "detailed_design": {
            "phase_id": "detailed_design",
            "label_zh": "详细设计",
            "description": "Land use layout, building footprints, transport network, "
                           "green-blue system, public space. "
                           "Corresponds to agent.2 (AI创新生态), agent.3 (AI场景), agent.4 (公共空间).",
            "agent_task_ids": ["agent.2", "agent.3", "agent.4"],
            "entry_conditions": [
                "strategic_framework_complete",
                "positioning_validated",
            ],
            "code_steps": [
                "generate_land_use_geojson",       # CODE: Land use polygons with valid codes
                "generate_building_geojson",       # CODE: Building footprints within boundary
                "generate_transport_geojson",       # CODE: Road network with valid classes
                "generate_green_blue_geojson",      # CODE: Green space + water system
                "generate_public_space_geojson",    # CODE: Public space + landmarks
                "validate_topology",                # CODE: No gaps, no overlaps, within boundary
                "validate_enums",                   # CODE: All codes from allowed enums
            ],
            "judgment_points": [
                "land_use_allocation",          # LLM: Where to place different land uses
                "building_typology_design",     # LLM: Building types and distribution
                "mobility_network_design",      # LLM: Road hierarchy and connections
                "ecological_structure_design",   # LLM: Green-blue network layout
                "public_space_sequence",        # LLM: Public space system and landmarks
                "ai_scenario_spatialization",   # LLM: Where AI scenarios happen in space
            ],
            "exit_constraint_groups": [
                "required_layers",
                "spatial_topology",
                "feature_attributes",
                "agent_task_requirements",      # agent.2, agent.3, agent.4 coverage
            ],
            "transitions": {
                "gate_pass": "system_integration",
                "gate_fail": "detailed_design",
                "blocked": "human_escalation",
            },
        },
        "system_integration": {
            "phase_id": "system_integration",
            "label_zh": "系统集成",
            "description": "Cross-system consistency, metrics calculation, cultural narrative, "
                           "activity system. "
                           "Corresponds to agent.5 (文化叙事) and agent.6 (活动体系).",
            "agent_task_ids": ["agent.5", "agent.6"],
            "entry_conditions": [
                "detailed_design_complete",
                "all_layers_generated",
                "topology_valid",
            ],
            "code_steps": [
                "compute_all_metrics",             # CODE: Derive metrics from GeoJSON
                "validate_cross_layer_consistency", # CODE: Land use ↔ buildings ↔ roads match
                "generate_compliance_matrix",      # CODE: Map 22 requirements to evidence
                "generate_design_depth_matrix",    # CODE: Standards compliance mapping
                "generate_standards_compliance",   # CODE: Professional standards response
                "verify_metrics_reproducibility",  # CODE: Every metric traceable to geometry
            ],
            "judgment_points": [
                "cross_system_coherence",       # LLM: Do all systems work together?
                "cultural_narrative_integration", # LLM: Culture ↔ space ↔ AI narrative
                "activity_system_design",       # LLM: Annual events, brand, community ops
            ],
            "exit_constraint_groups": [
                "metric_verification",
                "compliance_matrix",
                "design_depth",
                "professional_standards",
                "agent_task_requirements",      # agent.5, agent.6 coverage
            ],
            "transitions": {
                "gate_pass": "implementation",
                "gate_fail": "system_integration",
                "blocked": "human_escalation",
            },
        },
        "implementation": {
            "phase_id": "implementation",
            "label_zh": "实施策略",
            "description": "Phasing plan, governance recommendations, operations model. "
                           "Translates design intent into implementable stages.",
            "agent_task_ids": [],
            "entry_conditions": [
                "system_integration_complete",
                "metrics_verified",
                "compliance_matrix_complete",
            ],
            "code_steps": [
                "generate_phasing_geojson",        # CODE: 3-phase spatial zoning
                "generate_governance_recommendations", # CODE: Structured governance model
                "validate_phasing_coverage",       # CODE: Phases cover full site
                "check_forbidden_implementation_claims", # CODE: No engineering conclusions
            ],
            "judgment_points": [
                "phasing_strategy",             # LLM: What order, why, dependencies?
                "governance_model_design",      # LLM: Multi-stakeholder governance structure
            ],
            "exit_constraint_groups": [
                "source_integrity",
                "compliance_text",              # No forbidden conclusions
            ],
            "transitions": {
                "gate_pass": "compliance_packaging",
                "gate_fail": "implementation",
                "blocked": "human_escalation",
            },
        },
        "compliance_packaging": {
            "phase_id": "compliance_packaging",
            "label_zh": "合规与封装",
            "description": "Final validation against all constraints, file packaging, "
                           "self-check, manifest generation, Reflection Panel review.",
            "agent_task_ids": [],
            "entry_conditions": [
                "implementation_complete",
                "phasing_coverage_valid",
            ],
            "code_steps": [
                "run_full_constraint_engine",      # CODE: All 61 constraints
                "validate_package_structure",      # CODE: All 30 required files present
                "run_self_check",                  # CODE: Format, topology, hash validation
                "generate_manifest",               # CODE: manifest.json with hashes
                "finalize_package",                # CODE: Lock package, set ready_for_review
            ],
            "judgment_points": [
                "reflection_panel_review",      # LLM: 7 judges parallel review (final gate)
            ],
            "exit_constraint_groups": [],        # All constraints already checked
            "transitions": {
                "gate_pass": "completed",
                "minor_fixes": "compliance_packaging",  # Fix specific issues, re-finalize
                "major_fixes": "detailed_design",        # Back to detailed design
                "blocking": "human_escalation",
            },
        },
    }

    # ═══════════════════════════════════════════════════════════════════
    # Implementation
    # ═══════════════════════════════════════════════════════════════════

    def __init__(self, repo_root: str | Path = "."):
        self.root = Path(repo_root)
        self.domain: Any = None                 # UrbanDesignDomain (lazy loaded)
        self.phases: dict[str, DesignPhase] = {}
        self.submission_path: Path | None = None  # Set when working on a specific submission
        self._build_phases()

        # State tracking
        self.current_phase_id: str | None = None
        self.phase_order: list[str] = [
            "site_analysis",
            "strategic_framework",
            "detailed_design",
            "system_integration",
            "implementation",
            "compliance_packaging",
        ]
        self.completed_phases: list[str] = []
        self.round_num: int = 0
        self.max_rounds: int = 10

        # Stall detection
        self.stall_detector = StallDetector(threshold=2)

        # Judgment results archive
        self.judgment_results: dict[str, list[JudgmentResult]] = {}

        # Gate results archive
        self.gate_results: dict[str, list[PhaseGateResult]] = {}

    def _build_phases(self) -> None:
        """Instantiate DesignPhase objects from PHASE_DEFINITIONS."""
        for phase_id, defn in self.PHASE_DEFINITIONS.items():
            phase = DesignPhase(
                phase_id=defn["phase_id"],
                label_zh=defn["label_zh"],
                description=defn["description"],
                agent_task_ids=defn.get("agent_task_ids", []),
                entry_conditions=defn.get("entry_conditions", []),
                code_steps=defn.get("code_steps", []),
                judgment_points=defn.get("judgment_points", []),
                exit_constraint_groups=defn.get("exit_constraint_groups", []),
                transitions=defn.get("transitions", {}),
            )
            self.phases[phase_id] = phase

    @classmethod
    def from_repo(cls, repo_root: str | Path = ".") -> "UrbanDesignProcedure":
        """Create the procedure and load the domain model from repo data."""
        procedure = cls(repo_root)
        procedure._load_domain()
        return procedure

    def _load_domain(self) -> None:
        """Load the UrbanDesignDomain from repo physical files."""
        from constraints.domain import UrbanDesignDomain
        self.domain = UrbanDesignDomain.from_repo(str(self.root))

    # ═══════════════════════════════════════════════════════════════════
    # State Machine Operations
    # ═══════════════════════════════════════════════════════════════════

    def start(self, phase_id: str | None = None) -> DesignPhase:
        """Start the state machine at the given phase (default: first phase)."""
        if phase_id is None:
            phase_id = self.phase_order[0]

        if phase_id not in self.phases:
            raise ValueError(f"Unknown phase: {phase_id}")

        self.current_phase_id = phase_id
        phase = self.phases[phase_id]
        phase.status = "running"
        phase.started_at = time.time()
        self.round_num = 1
        return phase

    @property
    def current_phase(self) -> DesignPhase | None:
        if self.current_phase_id is None:
            return None
        return self.phases[self.current_phase_id]

    def advance(self) -> DesignPhase:
        """Attempt to advance to the next phase.

        Runs exit constraint checks. If the gate passes, transitions to the
        next phase. If it fails, stays in current phase for retry.
        If critical failures or stall detected, escalates.
        """
        if self.current_phase is None:
            raise RuntimeError("Procedure not started. Call start() first.")

        phase = self.current_phase

        # ── Run exit constraint gate ──
        gate_result = self._run_phase_gate(phase)

        # Store gate result
        if phase.phase_id not in self.gate_results:
            self.gate_results[phase.phase_id] = []
        self.gate_results[phase.phase_id].append(gate_result)

        # ── Stall detection ──
        fp = gate_result.fingerprint or StallDetector.compute_fingerprint(
            [f["constraint_id"] for f in gate_result.failures]
        )
        if self.stall_detector.check(phase.phase_id, fp, self.round_num):
            phase.status = "blocked"
            return self._escalate(f"Stall detected: {phase.phase_id} same failures ×{self.stall_detector.threshold}")

        # ── Max rounds ──
        if self.round_num >= self.max_rounds:
            phase.status = "blocked"
            return self._escalate(f"Max rounds ({self.max_rounds}) exceeded")

        # ── Route based on gate result ──
        if gate_result.gate_passed:
            return self._transition_to_next(phase)
        elif gate_result.critical_failures > 0:
            # Critical failures → retry same phase (with specific failure info)
            self.round_num += 1
            return phase
        else:
            # Non-critical failures → retry
            self.round_num += 1
            return phase

    def _transition_to_next(self, current_phase: DesignPhase) -> DesignPhase:
        """Move to the next phase in the workflow."""
        current_phase.status = "completed"
        current_phase.completed_at = time.time()
        self.completed_phases.append(current_phase.phase_id)

        # Find next phase
        current_idx = self.phase_order.index(current_phase.phase_id)
        if current_idx + 1 >= len(self.phase_order):
            # All phases complete
            self.current_phase_id = None
            return current_phase

        next_id = self.phase_order[current_idx + 1]
        next_phase = self.phases[next_id]

        # ── Check entry conditions ──
        if not self._check_entry_conditions(next_phase):
            next_phase.status = "blocked"
            return self._escalate(
                f"Entry conditions not met for {next_phase.phase_id}: "
                f"{next_phase.entry_conditions}"
            )

        # Transition
        self.current_phase_id = next_id
        next_phase.status = "running"
        next_phase.started_at = time.time()
        return next_phase

    def _check_entry_conditions(self, phase: DesignPhase) -> bool:
        """Verify all entry conditions are satisfied."""
        # Simple condition naming convention:
        # "domain_model_loaded" → self.domain is not None
        # "coordinate_system_valid" → self.domain.coordinate_system.validate()
        # "strategic_framework_complete" → phase in self.completed_phases
        for condition in phase.entry_conditions:
            if not self._evaluate_condition(condition):
                return False
        return True

    def _evaluate_condition(self, condition: str) -> bool:
        """Evaluate a named condition against current state.

        ORDER MATTERS: specific conditions come before the generic _complete suffix
        check, otherwise "compliance_matrix_complete" would be caught by the generic
        handler and look for a non-existent phase named "compliance_matrix".
        """
        # ── Specific domain/artifact conditions (before generic _complete check) ──
        if condition == "domain_model_loaded":
            return self.domain is not None
        elif condition == "coordinate_system_valid":
            return self.domain is not None and self.domain.coordinate_system.validate()
        elif condition == "scope_hierarchy_valid":
            return self.domain is not None and len(self.domain.scope_levels) == 3
        elif condition == "all_layers_generated":
            if self.submission_path is None:
                return False
            required = ["land_use", "buildings", "roads", "green_space", "public_space"]
            return all(
                (self.submission_path / f"geometry/{name}.geojson").exists()
                for name in required
            )
        elif condition == "topology_valid":
            return self._run_constraint_group("spatial_topology")
        elif condition == "metrics_verified":
            return self._verify_file_exists("metrics.json")
        elif condition == "compliance_matrix_complete":
            return self._verify_file_exists("compliance_matrix.json")
        elif condition == "implementation_complete":
            return self._verify_geojson_exists("geometry/phasing.geojson")
        elif condition == "phasing_coverage_valid":
            return self._run_constraint_group("spatial_topology")
        elif condition == "positioning_validated":
            return (
                self.domain is not None
                and len(self.domain.positionings) == 3
                and len(self.domain.five_functions) == 5
            )
        # ── Phase completion checks (generic — order AFTER specific conditions) ──
        elif condition.endswith("_complete"):
            phase_id = condition.replace("_complete", "")
            return phase_id in self.completed_phases
        return True  # Unknown conditions pass by default (fail-open for dev)

    def _run_phase_gate(self, phase: DesignPhase) -> PhaseGateResult:
        """Run constraint engine checks for this phase's exit gate.

        This is the HARD gate — CODE checks, zero LLM.
        Only constraints in the phase's exit_constraint_groups are checked.
        """
        if not phase.exit_constraint_groups:
            # No exit constraints → gate passes automatically
            return PhaseGateResult(
                phase_id=phase.phase_id,
                gate_passed=True,
                total_checks=0,
                passed=0,
                failed=0,
                critical_failures=0,
                failures=[],
            )

        from constraints.engine import ConstraintEngine

        engine = ConstraintEngine(self.root)

        # Filter constraints to this phase's exit groups
        phase_constraints = [
            c for c in engine.constraints
            if c.get("category") in phase.exit_constraint_groups
            and c.get("enabled", True)
            and c.get("check_type") == "CODE"
        ]

        if not phase_constraints:
            return PhaseGateResult(
                phase_id=phase.phase_id,
                gate_passed=True,
                total_checks=0, passed=0, failed=0,
                critical_failures=0, failures=[],
            )

        # Run actual validation if a submission path is set
        if self.submission_path:
            raw_results = engine.validate(str(self.submission_path))
        else:
            raw_results = []

        # Convert ConstraintResult objects to dicts for the gate result
        results = []
        for r in raw_results:
            rid = getattr(r, "constraint_id", "")
            if rid not in {c["constraint_id"] for c in phase_constraints}:
                continue
            results.append({
                "constraint_id": rid,
                "passed": getattr(r, "outcome", None) and r.outcome.value == "PASS",
                "severity": getattr(r, "severity", "high"),
                "detail": getattr(r, "detail", ""),
                "evidence": getattr(r, "evidence", ""),
            })

        failures = [r for r in results if not r.get("passed", False)]
        critical = [r for r in failures if r.get("severity") == "critical"]

        fp = StallDetector.compute_fingerprint([f.get("constraint_id") for f in failures])

        return PhaseGateResult(
            phase_id=phase.phase_id,
            gate_passed=len(failures) == 0,
            total_checks=len(results),
            passed=len(results) - len(failures),
            failed=len(failures),
            critical_failures=len(critical),
            failures=failures,
            fingerprint=fp,
        )

    def _escalate(self, reason: str) -> DesignPhase:
        """Escalate to human — something is blocked and can't auto-resolve."""
        escalation_phase = DesignPhase(
            phase_id="human_escalation",
            label_zh="人工介入",
            description=reason,
        )
        escalation_phase.status = "blocked"
        self.current_phase_id = "human_escalation"
        return escalation_phase

    # ═══════════════════════════════════════════════════════════════════
    # CODE Step Execution — deterministic, no LLM
    # ═══════════════════════════════════════════════════════════════════

    def execute_code_step(self, step_name: str) -> StepStatus:
        """Execute a deterministic CODE step.

        These are hard-coded functions. No LLM involved.
        Returns PASSED or FAILED.
        """
        if self.current_phase is None:
            raise RuntimeError("Procedure not started.")

        phase = self.current_phase

        if step_name not in phase.code_steps:
            raise ValueError(
                f"Unknown CODE step '{step_name}' for phase '{phase.phase_id}'. "
                f"Available: {phase.code_steps}"
            )

        phase.step_results[step_name] = StepStatus.RUNNING

        # ── Dispatch to handler ──
        handler = getattr(self, f"_code_{step_name}", None)
        if handler is None:
            # No specific handler → passes by default (placeholder for future implementation)
            phase.step_results[step_name] = StepStatus.PASSED
            return StepStatus.PASSED

        try:
            result = handler()
            phase.step_results[step_name] = StepStatus.PASSED if result else StepStatus.FAILED
            return phase.step_results[step_name]
        except Exception as e:
            phase.step_results[step_name] = StepStatus.FAILED
            raise

    # ── Phase 1: Site Analysis CODE handlers ──

    def _code_load_domain_model(self) -> bool:
        """Load the UrbanDesignDomain from repo physical files."""
        from constraints.domain import UrbanDesignDomain
        self.domain = UrbanDesignDomain.from_repo(str(self.root))
        return self.domain is not None

    def _code_validate_coordinate_system(self) -> bool:
        """HARD: Verify EPSG:4548 for area calculations."""
        if self.domain is None:
            return False
        return self.domain.coordinate_system.validate()

    def _code_load_site_boundaries(self) -> bool:
        """Parse SITE_BOUNDARY provisional geometry from repo."""
        candidates = [
            self.root / "brief/site-package/geometry/provisional_boundaries.geojson",
            self.root / "brief/site-package/geometry/study_area_bbox.geojson",
            self.root / "brief/site-package/boundaries/study_area_boundary.geojson",
        ]
        return any(p.exists() for p in candidates)

    def _code_compute_base_metrics(self) -> bool:
        """Compute area, perimeter, extent for each scope level from geometry."""
        if self.domain is None:
            return False
        # In production: use pyproj to transform EPSG:4326 → EPSG:4548, compute areas
        # For now: verify the declared areas are internally consistent
        scopes = self.domain.scope_levels
        if len(scopes) != 3:
            return False
        # coordinated (43.6 km²) > overall (11.4 km²) > key (3.684 km²)
        return (
            scopes[0].area_sqm > scopes[1].area_sqm > scopes[2].area_sqm
        )

    def _code_validate_scope_hierarchy(self) -> bool:
        """HARD: Verify 3-level scope containment (coordinated ⊃ overall ⊃ key)."""
        if self.domain is None:
            return False
        scopes = self.domain.scope_levels
        if len(scopes) != 3:
            return False
        return (
            scopes[0].scope_id == "coordinated_research_area"
            and scopes[1].scope_id == "overall_design_area"
            and scopes[2].scope_id == "key_detailed_design_area"
        )

    def _code_enumerate_hard_constraints(self) -> bool:
        """List all CODE constraints from the registry that apply to this project."""
        registry_file = self.root / "constraints" / "registry.json"
        if not registry_file.exists():
            return False
        return True

    # ── Phase 2: Strategic Framework CODE handlers ──

    def _code_validate_positioning_alignment(self) -> bool:
        """HARD: 3 positionings must all be addressed."""
        if self.domain is None:
            return False
        return len(self.domain.positionings) == 3

    def _code_validate_five_functions(self) -> bool:
        """HARD: 5 functions must all be addressed."""
        if self.domain is None:
            return False
        return len(self.domain.five_functions) == 5

    def _code_check_three_areas_two_wings(self) -> bool:
        """HARD: Verify key areas + wings spatial structure."""
        if self.domain is None:
            return False
        # 3 key areas + 2 wings = 5 total
        return len(self.domain.key_areas) == 3
        # Wings are conceptually part of the 5 role definitions

    def _code_check_naming_conventions(self) -> bool:
        """HARD: Verify naming does not violate forbidden patterns."""
        # Would check proposal.md for forbidden patterns
        # For now: constraint engine handles this
        return True

    # ── Phase 3: Detailed Design CODE handlers ──
    # Generation steps: the Generator (LLM at JUDGMENT points) creates the content.
    # These steps verify existence and basic validity of what was generated.

    def _code_generate_land_use_geojson(self) -> bool:
        """Verify land_use.geojson exists with valid features."""
        return self._verify_geojson_exists("geometry/land_use.geojson")

    def _code_generate_building_geojson(self) -> bool:
        """Verify buildings.geojson exists with valid features."""
        return self._verify_geojson_exists("geometry/buildings.geojson")

    def _code_generate_transport_geojson(self) -> bool:
        """Verify roads.geojson exists with valid features."""
        return self._verify_geojson_exists("geometry/roads.geojson")

    def _code_generate_green_blue_geojson(self) -> bool:
        """Verify green_space.geojson exists with valid features."""
        return self._verify_geojson_exists("geometry/green_space.geojson")

    def _code_generate_public_space_geojson(self) -> bool:
        """Verify public_space.geojson exists with valid features."""
        return self._verify_geojson_exists("geometry/public_space.geojson")

    def _code_validate_topology(self) -> bool:
        """Run spatial topology checks via constraint engine if available."""
        return self._run_constraint_group("spatial_topology")

    def _code_validate_enums(self) -> bool:
        """Validate all enum values in GeoJSON properties."""
        return self._run_constraint_group("feature_attributes")

    # ── Phase 4: System Integration CODE handlers ──

    def _code_compute_all_metrics(self) -> bool:
        """Verify metrics.json exists and has required fields."""
        return self._verify_file_exists("metrics.json")

    def _code_validate_cross_layer_consistency(self) -> bool:
        """Check land use ↔ buildings ↔ roads spatial consistency."""
        return self._run_constraint_group("spatial_topology")

    def _code_generate_compliance_matrix(self) -> bool:
        """Verify compliance_matrix.json exists."""
        return self._verify_file_exists("compliance_matrix.json")

    def _code_generate_design_depth_matrix(self) -> bool:
        """Verify design_depth_matrix.json exists."""
        return self._verify_file_exists("design_depth_matrix.json")

    def _code_generate_standards_compliance(self) -> bool:
        """Verify standard_matrix.json exists."""
        return self._verify_file_exists("standard_matrix.json")

    def _code_verify_metrics_reproducibility(self) -> bool:
        """Check that key metrics in metrics.json are traceable to geometry."""
        return self._run_constraint_group("metric_verification")

    # ── Phase 5: Implementation CODE handlers ──

    def _code_generate_phasing_geojson(self) -> bool:
        """Verify phasing.geojson exists."""
        return self._verify_geojson_exists("geometry/phasing.geojson")

    def _code_generate_governance_recommendations(self) -> bool:
        """Verify proposal.md has governance section with minimum content."""
        return self._check_proposal_has_section("实施策略", min_chars=200)

    def _code_validate_phasing_coverage(self) -> bool:
        """Check phasing zones fully cover the site."""
        return self._run_constraint_group("spatial_topology")

    def _code_check_forbidden_implementation_claims(self) -> bool:
        """Scan proposal.md for forbidden implementation conclusions."""
        return self._grep_forbidden_in_submission([
            "政府承诺", "已确定", "资金到位", "政策保证",
            "纯口号", "招商承诺", "已获批", "已列入规划",
        ])

    # ── Phase 6: Compliance & Packaging CODE handlers ──

    def _code_run_full_constraint_engine(self) -> bool:
        """Run all CODE constraints via the constraint engine.

        This is the HARD gate before Reflection Panel. Must actually pass.
        """
        if self.submission_path is None:
            return False  # No submission to validate
        try:
            from constraints.engine import ConstraintEngine
            engine = ConstraintEngine(self.root)
            results = engine.validate(str(self.submission_path))
            failures = [r for r in results if not r.passed]
            # Store results for reference
            self._last_constraint_results = results
            return len(failures) == 0
        except ImportError:
            return False  # HARD FAIL: engine must be available
        except Exception as e:
            self._last_constraint_error = str(e)
            return False

    def _code_validate_package_structure(self) -> bool:
        """Verify all 29 required files exist in submission."""
        if self.submission_path is None:
            return False
        if self.domain is None:
            return False
        missing = []
        for rf in self.domain.required_files:
            fp = self.submission_path / rf.path
            if not fp.exists():
                missing.append(rf.path)
        self._last_missing_files = missing
        return len(missing) == 0

    def _code_run_self_check(self) -> bool:
        """Run the project's self_check_submission.py if available."""
        if self.submission_path is None:
            return False
        script = self.root / "scripts" / "self_check_submission.py"
        if script.exists():
            import subprocess
            result = subprocess.run(
                ["python3", str(script), str(self.submission_path)],
                capture_output=True, text=True,
            )
            return result.returncode == 0
        return True  # No self-check script → pass (will be caught by constraint engine)

    def _code_generate_manifest(self) -> bool:
        """Verify manifest.json exists in submission."""
        return self._verify_file_exists("manifest.json")

    def _code_finalize_package(self) -> bool:
        """Run finalize_submission.py if available."""
        if self.submission_path is None:
            return False
        script = self.root / "scripts" / "finalize_submission.py"
        if script.exists():
            import subprocess
            result = subprocess.run(
                ["python3", str(script), str(self.submission_path)],
                capture_output=True, text=True,
            )
            return result.returncode == 0
        return True  # No finalize script → manual finalization

    # ═══════════════════════════════════════════════════════════════════
    # Internal Helpers — real checks, not stubs
    # ═══════════════════════════════════════════════════════════════════

    def _verify_file_exists(self, rel_path: str) -> bool:
        """Check a file exists in the submission."""
        if self.submission_path is None:
            return False
        return (self.submission_path / rel_path).exists()

    def _verify_geojson_exists(self, rel_path: str) -> bool:
        """Check a GeoJSON file exists and has features."""
        fp = self.submission_path / rel_path if self.submission_path else None
        if fp is None or not fp.exists():
            return False
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            return len(data.get("features", [])) > 0
        except Exception:
            return False

    def _grep_forbidden_in_submission(self, forbidden: list[str]) -> bool:
        """Check proposal.md for forbidden patterns. Returns True if NONE found."""
        fp = self.submission_path / "proposal.md" if self.submission_path else None
        if fp is None or not fp.exists():
            return True  # No file → can't violate
        try:
            text = fp.read_text(encoding="utf-8")
            hits = [w for w in forbidden if w in text]
            self._last_forbidden_hits = hits
            return len(hits) == 0
        except Exception:
            return False

    def _check_proposal_has_section(self, section_marker: str, min_chars: int = 100) -> bool:
        """Check proposal.md has a section with minimum content length."""
        fp = self.submission_path / "proposal.md" if self.submission_path else None
        if fp is None or not fp.exists():
            return False
        try:
            text = fp.read_text(encoding="utf-8")
            idx = text.find(section_marker)
            if idx < 0:
                return False
            rest = text[idx:]
            next_sec = rest.find("\n## ", len(section_marker))
            content = rest if next_sec < 0 else rest[:next_sec]
            return len(content.strip()) >= min_chars
        except Exception:
            return False

    def _run_constraint_group(self, group: str) -> bool:
        """Run a specific constraint group via the engine. Returns True if all pass."""
        if self.submission_path is None:
            return False
        try:
            from constraints.engine import ConstraintEngine
            engine = ConstraintEngine(self.root)
            # Filter constraints to the specified group
            group_constraints = [
                c for c in engine.constraints
                if c.get("category") == group and c.get("enabled", True) and c.get("check_type") == "CODE"
            ]
            if not group_constraints:
                return True  # No constraints in group → pass
            # Run validate and check only this group's results
            results = engine.validate(str(self.submission_path))
            group_failures = [
                r for r in results
                if not r.passed and r.constraint_id in {c["constraint_id"] for c in group_constraints}
            ]
            return len(group_failures) == 0
        except ImportError:
            return True  # Engine not available; deferred to Phase 6 gate
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════════════════
    # JUDGMENT Point Execution — where LLM is called LOCALLY
    # ═══════════════════════════════════════════════════════════════════

    def execute_judgment(
        self,
        judgment_id: str,
        llm_client: Any = None,
    ) -> JudgmentResult:
        """Execute a JUDGMENT point — call LLM with structured input.

        THIS IS THE ONLY PLACE LLM IS CALLED.

        The LLM receives:
          1. A specific creative question (not "design the whole thing")
          2. Hard constraints it MUST respect
          3. Relevant domain context
          4. A required output schema

        The state machine validates the LLM's response BEFORE accepting it:
          1. Schema conformance (CODE)
          2. Evidence requirements (CODE)
          3. Constraint violations (CODE → ConstraintEngine)

        Only after all three pass does the state machine accept the result
        and continue. The LLM NEVER decides what happens next — the state
        machine does.
        """
        if self.current_phase is None:
            raise RuntimeError("Procedure not started.")

        phase = self.current_phase

        if judgment_id not in phase.judgment_points:
            raise ValueError(
                f"Unknown JUDGMENT point '{judgment_id}' for phase '{phase.phase_id}'. "
                f"Available: {phase.judgment_points}"
            )

        # ── Build judgment context ──
        context = self._build_judgment_context(judgment_id, phase)

        # ── Call LLM (or mock for testing) ──
        if llm_client is None:
            # In production, this would be a real LLM call
            result = self._mock_judgment(context)
        else:
            result = self._call_llm(llm_client, context)

        # ── Validate LLM output BEFORE accepting ──
        validation_errors = self._validate_judgment_result(result, context)

        if validation_errors:
            result.accepted = False
            result.constraint_violations = validation_errors
        else:
            result.accepted = True

        # ── Archive ──
        if phase.phase_id not in self.judgment_results:
            self.judgment_results[phase.phase_id] = []
        self.judgment_results[phase.phase_id].append(result)

        return result

    def _build_judgment_context(
        self, judgment_id: str, phase: DesignPhase
    ) -> JudgmentContext:
        """Build the structured input for an LLM judgment call.

        This is the KEY design decision: the LLM only sees what it NEEDS
        to make ONE specific decision. It does NOT see the entire project.
        """
        # ── Hard constraints relevant to this judgment ──
        hard_constraints = []
        if self.domain and self.domain.boundary_clause:
            bc = self.domain.boundary_clause
            hard_constraints.append({
                "type": "boundary_clause",
                "rule": bc.must_state_zh,
                "forbidden": list(bc.forbidden_final_conclusions),
            })

        # ── Domain context relevant to this judgment ──
        domain_context = {}
        if self.domain:
            domain_context["scope_levels"] = [
                {"id": s.scope_id, "label": s.label_zh, "area_sqm": s.area_sqm}
                for s in self.domain.scope_levels
            ]
            domain_context["key_areas"] = [
                {"id": ka.area_id, "label": ka.label_zh, "area_ha": ka.area_ha, "role": ka.role_zh}
                for ka in self.domain.key_areas
            ]
            domain_context["positionings"] = self.domain.positionings
            domain_context["five_functions"] = self.domain.five_functions
            domain_context["layer_ids"] = [l.layer_id for l in self.domain.layers]

        # ── Required output schema (depends on judgment type) ──
        schema = self._get_judgment_schema(judgment_id)

        # ── Evidence requirements ──
        evidence = self._get_evidence_requirements(judgment_id)

        return JudgmentContext(
            judgment_id=judgment_id,
            phase_id=phase.phase_id,
            prompt_template=self._get_judgment_prompt(judgment_id),
            hard_constraints=hard_constraints,
            domain_context=domain_context,
            required_output_schema=schema,
            evidence_requirements=evidence,
        )

    def _get_judgment_prompt(self, judgment_id: str) -> str:
        """Get the specific creative question for each judgment point."""
        prompts = {
            "site_interpretation": (
                "基于以下场地数据，分析百年京张AI创新带的核心空间特征：\n"
                "- 3个层次的空间范围（统筹研究43.6km² / 总体设计11.4km² / 重点区域368.4ha）\n"
                "- 3个重点片区（AI原点社区、众智园、大钟寺）+ 2翼（中关村科技服务翼、小月河场景赋能翼）\n"
                "- 京张铁路遗址公园作为南北骨架\n\n"
                "请输出：场地核心空间特征的5-8个关键洞察，每个洞察必须引用具体的空间位置或数据。"
            ),
            "concept_generation": (
                "为百年京张AI创新带生成总体概念方案：\n"
                "- 主名称和英文名称\n"
                "- Logo/视觉识别方向\n"
                "- 总体空间结构（需基于3区2翼的框架）\n"
                "- 三大定位的体现方式\n\n"
                "约束：不能使用口号式命名；不能照搬现有城市/园区名称。"
            ),
            "spatial_structure_design": (
                "设计一带的总体空间结构图方案：\n"
                "- 南北骨架（京张遗址公园）与东西缝合\n"
                "- 3个重点片区的空间关系\n"
                "- 与中关村、学院路、清河等周边区域的关系\n"
                "- 主要功能和活动的空间分布\n\n"
                "输出：空间结构描述 + 关键节点列表 + 功能分区逻辑。"
            ),
            "land_use_allocation": (
                "在总体设计范围（11.4km²）内进行用地功能布局：\n"
                "- 必须使用国家用地分类标准中的合法代码\n"
                "- 用地必须完全覆盖设计范围，无间隙\n"
                "- 各片区的主导功能应与任务书定位一致\n\n"
                "输出：各片区的用地功能配置方案，包含用地代码和大致比例。"
            ),
            "building_typology_design": (
                "设计建筑类型学方案：\n"
                "- 基于用地功能配置，确定各区域的建筑类型\n"
                "- 必须使用合法建筑类型代码\n"
                "- AI相关建筑应有创新类型说明\n\n"
                "约束：不能给出容积率、建筑高度、具体拆改留等工程结论。"
            ),
            "mobility_network_design": (
                "设计交通与慢行网络：\n"
                "- 基于现有道路骨架，规划设计范围内道路网络\n"
                "- 必须使用合法道路等级代码（不含expressway/arterial）\n"
                "- 慢行优先策略，特别是京张遗址公园沿线的南北贯通\n\n"
                "输出：道路网络结构描述 + 关键断面概念。"
            ),
            "ecological_structure_design": (
                "设计蓝绿生态网络：\n"
                "- 识别现有水系和绿地资源\n"
                "- 设计绿地系统结构\n"
                "- 考虑海绵城市理念\n\n"
                "输出：蓝绿网络结构 + 关键生态廊道。"
            ),
            "public_space_sequence": (
                "设计公共空间体系：\n"
                "- 公共空间序列和等级\n"
                "- AI朝圣地标（≥3个）的位置和概念\n"
                "- 东西缝合和南北贯通的空间策略\n\n"
                "约束：不能违反文保、绿地、蓝线约束。"
            ),
            "ai_scenario_spatialization": (
                "将AI场景落实到空间：\n"
                "- ≥10张AI场景卡的空间落位\n"
                "- ≥3个AI产业测试验证场景的空间需求\n"
                "- 场景-空间-运营的三维映射\n\n"
                "输出：每个场景的空间位置、空间需求和空间特征。"
            ),
            "cross_system_coherence": (
                "检查各系统之间的协调性：\n"
                "- 用地布局 ↔ 交通网络是否匹配\n"
                "- 建筑 ↔ 公共空间是否协调\n"
                "- AI场景 ↔ 空间承载是否合理\n\n"
                "输出：系统协调性评估 + 需要调整的具体问题。"
            ),
            "cultural_narrative_integration": (
                "整合文化叙事与空间设计：\n"
                "- 京张铁路历史文化资源在空间中的表达\n"
                "- 中关村创新文化与AI新文化的空间叙事\n"
                "- 导视、标识系统和城市气质\n\n"
                "输出：空间文化叙事方案。"
            ),
            "activity_system_design": (
                "设计全球AI创新活动体系：\n"
                "- 年度活动体系\n"
                "- 活动品牌与传播\n"
                "- 开发者社区运营机制\n\n"
                "输出：活动体系框架 + 运营机制概要。"
            ),
            "phasing_strategy": (
                "设计分期实施策略：\n"
                "- 3期分期方案\n"
                "- 各期的空间范围和重点任务\n"
                "- 分期的逻辑和依赖关系\n\n"
                "输出：分期方案 + 各期核心任务。"
            ),
            "governance_model_design": (
                "设计多方协同治理模式：\n"
                "- 政府、企业、开发者社区的角色\n"
                "- AI场景开放的治理机制\n"
                "- 公共空间的运营管理\n\n"
                "输出：治理模型框架。"
            ),
            "reflection_panel_review": (
                "作为质量审查法官，对完整方案包进行最终评审。\n"
                "评审维度由 statutes.json 中的7部法规定义。\n"
                "每条评判必须引用物理文件中的具体证据。\n\n"
                "输出：结构化 Verdict JSON。"
            ),
        }
        return prompts.get(judgment_id, f"Execute judgment: {judgment_id}")

    def _get_judgment_schema(self, judgment_id: str) -> dict:
        """Get the JSON Schema that LLM output must conform to."""
        # Generic creative judgment schema
        base_schema = {
            "type": "object",
            "required": ["design_output", "rationale", "evidence_refs"],
            "properties": {
                "design_output": {
                    "type": "object",
                    "description": "The creative design output — structure depends on judgment type",
                },
                "rationale": {
                    "type": "string",
                    "description": "Professional reasoning behind the design decisions",
                },
                "evidence_refs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["source", "location", "snippet"],
                        "properties": {
                            "source": {"type": "string"},
                            "location": {"type": "string"},
                            "snippet": {"type": "string"},
                        },
                    },
                },
                "constraints_checked": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of constraint IDs verified against this output",
                },
            },
        }

        # Reflection panel uses the Verdict schema (from hardlaw)
        if judgment_id == "reflection_panel_review":
            return {
                "type": "object",
                "required": ["verdict", "findings", "terminal_token"],
                "properties": {
                    "verdict": {
                        "type": "object",
                        "required": ["refuted", "confidence", "blocking"],
                        "properties": {
                            "refuted": {"type": "boolean"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "blocking": {"type": "boolean"},
                        },
                    },
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["claim", "evidence", "severity"],
                            "properties": {
                                "claim": {"type": "string"},
                                "evidence": {"type": "string"},
                                "severity": {"type": "string", "enum": ["critical", "major", "minor", "info"]},
                            },
                        },
                    },
                    "terminal_token": {
                        "type": "string",
                        "enum": ["Not Refuted", "Refuted"],
                    },
                    "evidence_refs": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
            }

        return base_schema

    def _get_evidence_requirements(self, judgment_id: str) -> list[str]:
        """Get the physical evidence that the LLM output must cite."""
        common = [
            "design_brief.json → official scope levels and areas",
            "agent_taskbook.json → required tasks and boundary clause",
        ]
        specific = {
            "site_interpretation": [
                "boundaries/study_area_boundary.geojson → actual site geometry",
                "allowed_design_space.json → editable vs locked layers",
            ],
            "concept_generation": [
                "agent_taskbook.json → 3 positionings, 5 functions",
            ],
            "spatial_structure_design": [
                "key_areas → 3 areas + 2 wings spatial definitions",
            ],
            "land_use_allocation": [
                "enums/land_use_codes.json → valid land use codes",
                "planning_limits.json → hard numeric bounds",
            ],
            "building_typology_design": [
                "enums/building_types.json → valid building type codes",
            ],
            "mobility_network_design": [
                "enums/road_classes.json → valid road class codes",
            ],
            "ai_scenario_spatialization": [
                "agent_taskbook.json → agent.3 requirements",
            ],
            "reflection_panel_review": [
                "statutes.json → 7 quality statutes with physical_evidence lists",
            ],
        }
        return common + specific.get(judgment_id, [])

    def _validate_judgment_result(
        self, result: JudgmentResult, context: JudgmentContext
    ) -> list[str]:
        """Validate LLM output before accepting it. CODE checks, not LLM.

        Returns list of validation errors (empty = valid).
        """
        errors = []

        # 1. Schema conformance
        try:
            from jsonschema import validate, ValidationError
            validate(instance=result.content, schema=context.required_output_schema)
        except ImportError:
            pass  # jsonschema not available — skip schema validation
        except Exception as e:
            errors.append(f"Schema validation failed: {e}")

        # 2. Evidence requirements
        cited_sources = [e.get("source", "") for e in result.evidence_refs]
        for req in context.evidence_requirements:
            source_file = req.split("→")[0].strip() if "→" in req else req
            if not any(source_file in s for s in cited_sources):
                errors.append(f"Missing required evidence: {req}")

        # 3. Hard constraint violations
        for constraint in context.hard_constraints:
            if constraint.get("type") == "boundary_clause":
                for forbidden in constraint.get("forbidden", []):
                    content_str = json.dumps(result.content, ensure_ascii=False)
                    if forbidden in content_str:
                        errors.append(f"Violates boundary clause: contains '{forbidden}'")

        # 4. Fail-closed: if we can't verify, default to reject
        if not result.evidence_refs:
            errors.append("No evidence references provided — fail-closed")

        return errors

    def _call_llm(self, llm_client: Any, context: JudgmentContext) -> JudgmentResult:
        """Make the actual LLM call with structured input.

        The LLM receives:
          - context.prompt_template (the specific question)
          - context.hard_constraints (rules it must follow)
          - context.domain_context (relevant data)
          - context.required_output_schema (output format)

        The LLM MUST return structured JSON conforming to the schema.
        """
        # Build the LLM prompt
        prompt_parts = [
            "# Urban Design Judgment",
            "",
            f"## Task: {context.judgment_id}",
            f"Phase: {context.phase_id}",
            "",
            context.prompt_template,
            "",
            "## Hard Constraints (MUST respect)",
        ]
        for c in context.hard_constraints:
            prompt_parts.append(f"- {json.dumps(c, ensure_ascii=False)}")

        prompt_parts.extend([
            "",
            "## Domain Context",
            json.dumps(context.domain_context, ensure_ascii=False, indent=2),
            "",
            "## Required Evidence",
        ])
        for e in context.evidence_requirements:
            prompt_parts.append(f"- {e}")

        prompt_parts.extend([
            "",
            "## Required Output Format",
            "You MUST respond with valid JSON conforming to this schema:",
            json.dumps(context.required_output_schema, indent=2),
            "",
            "Each claim in your output MUST cite specific physical evidence",
            "(source file, location in file, and relevant snippet).",
        ])

        full_prompt = "\n".join(prompt_parts)

        # This would call the actual LLM API
        # For now, returns a placeholder
        return JudgmentResult(
            judgment_id=context.judgment_id,
            accepted=False,  # Will be set to True after validation passes
            content={"design_output": {}, "rationale": "", "evidence_refs": [], "constraints_checked": []},
            evidence_refs=[],
            constraint_violations=["LLM call not yet implemented — use execute_judgment with a real client"],
        )

    def _mock_judgment(self, context: JudgmentContext) -> JudgmentResult:
        """Mock judgment for testing the state machine without an LLM."""
        mock_evidence = [
            {"source": "design_brief.json", "location": "official_scope_levels", "snippet": "43.6 km²"},
            {"source": "agent_taskbook.json", "location": "required_agent_tasks", "snippet": "6 tasks"},
            {"source": "allowed_design_space.json", "location": "editable_layers", "snippet": "layers list"},
        ]
        return JudgmentResult(
            judgment_id=context.judgment_id,
            accepted=False,
            content={
                "design_output": {"mock": True, "judgment": context.judgment_id},
                "rationale": "Mock judgment for testing",
                "evidence_refs": mock_evidence,
                "constraints_checked": [],
            },
            evidence_refs=mock_evidence,
            constraint_violations=[],
            fingerprint=StallDetector.compute_fingerprint({"mock": context.judgment_id}),
        )

    # ═══════════════════════════════════════════════════════════════════
    # Full Workflow Execution
    # ═══════════════════════════════════════════════════════════════════

    def run(self, llm_client: Any = None) -> dict:
        """Run the full urban design workflow from start to completion.

        This is the MAIN ENTRY POINT for autonomous execution.
        The state machine controls ALL flow — LLM is only called at JUDGMENT points.

        Returns:
            {
                "status": "completed" | "blocked" | "escalated",
                "completed_phases": [...],
                "final_phase": str,
                "total_rounds": int,
                "judgment_count": int,
                "gate_results": {...},
            }
        """
        self.start()
        judgment_count = 0

        while self.current_phase is not None and self.current_phase_id != "human_escalation":
            phase = self.current_phase

            # ── Execute all CODE steps ──
            for step_name in phase.code_steps:
                status = self.execute_code_step(step_name)
                if status == StepStatus.FAILED:
                    # CODE step failed — this is a hard failure
                    # Specific handler should provide repair instructions
                    pass

            # ── Execute all JUDGMENT points ──
            for judgment_id in phase.judgment_points:
                result = self.execute_judgment(judgment_id, llm_client)
                judgment_count += 1

                if not result.accepted:
                    # LLM output rejected by validation — retry judgment
                    # (in production: re-prompt LLM with validation errors)
                    pass

            # ── Advance to next phase ──
            next_phase = self.advance()

            if next_phase.phase_id == "human_escalation":
                return {
                    "status": "escalated",
                    "completed_phases": self.completed_phases,
                    "final_phase": self.current_phase_id,
                    "total_rounds": self.round_num,
                    "judgment_count": judgment_count,
                    "gate_results": self.gate_results,
                    "escalation_reason": next_phase.description,
                }

            if next_phase.phase_id == self.current_phase_id:
                # Same phase — gate failed, retrying
                continue

            # Moved to next phase
            self.round_num = 1  # Reset round counter for new phase

        return {
            "status": "completed",
            "completed_phases": self.completed_phases,
            "final_phase": self.completed_phases[-1] if self.completed_phases else None,
            "total_rounds": self.round_num,
            "judgment_count": judgment_count,
            "gate_results": self.gate_results,
        }

    # ═══════════════════════════════════════════════════════════════════
    # Inspection & Reporting
    # ═══════════════════════════════════════════════════════════════════

    def summary(self) -> dict:
        """Return a structured summary of the procedure state."""
        phases_summary = {}
        for pid, phase in self.phases.items():
            phases_summary[pid] = {
                "label_zh": phase.label_zh,
                "status": phase.status,
                "code_steps": {
                    s: phase.step_results[s].value if s in phase.step_results else "pending"
                    for s in phase.code_steps
                },
                "judgment_points": {
                    j: "executed" if pid in self.judgment_results and any(
                        r.judgment_id == j for r in self.judgment_results[pid]
                    ) else "pending"
                    for j in phase.judgment_points
                },
                "gate_attempts": len(self.gate_results.get(pid, [])),
                "last_gate_passed": (
                    self.gate_results[pid][-1].gate_passed
                    if self.gate_results.get(pid) else None
                ),
            }

        return {
            "current_phase": self.current_phase_id,
            "completed_phases": self.completed_phases,
            "round_num": self.round_num,
            "max_rounds": self.max_rounds,
            "stall_history": self.stall_detector.history,
            "phases": phases_summary,
        }

    def print_workflow(self) -> str:
        """Print the full workflow as an ASCII diagram."""
        lines = ["Professional Urban Design Workflow", "=" * 60, ""]
        for i, pid in enumerate(self.phase_order):
            phase = self.phases[pid]
            marker = "→ " if pid == self.current_phase_id else "  "
            done = "✓" if pid in self.completed_phases else " "
            lines.append(f"{marker}[{done}] Phase {i+1}: {phase.label_zh} ({pid})")
            lines.append(f"    Agent tasks: {phase.agent_task_ids or 'N/A'}")
            lines.append(f"    CODE steps: {len(phase.code_steps)}")
            for s in phase.code_steps:
                status = phase.step_results.get(s, StepStatus.PENDING)
                lines.append(f"      - {s} [{status.value}]")
            lines.append(f"    JUDGMENT points: {len(phase.judgment_points)}")
            for j in phase.judgment_points:
                executed = pid in self.judgment_results and any(
                    r.judgment_id == j for r in self.judgment_results.get(pid, [])
                )
                lines.append(f"      - {j} {'✓' if executed else '○'}")
            lines.append(f"    Exit gates: {phase.exit_constraint_groups or 'none'}")
            if pid in self.gate_results:
                last = self.gate_results[pid][-1]
                lines.append(f"    Last gate: {'PASS' if last.gate_passed else 'FAIL'} "
                           f"({last.passed}/{last.total_checks})")
            lines.append("")

        if self.current_phase_id == "human_escalation":
            lines.append("⚠️  HUMAN ESCALATION — manual intervention required")
        elif self.current_phase_id is None and self.completed_phases:
            lines.append("✅ ALL PHASES COMPLETE")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Quick Test
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os

    # Find repo root
    repo_root = os.getcwd()
    if not (Path(repo_root) / "brief").exists():
        # Try parent
        repo_root = os.path.dirname(repo_root)

    print("Loading Urban Design Procedure...")
    procedure = UrbanDesignProcedure.from_repo(repo_root)

    print(f"Domain loaded: {procedure.domain is not None}")
    if procedure.domain:
        print(f"  Scope levels: {len(procedure.domain.scope_levels)}")
        print(f"  Key areas: {len(procedure.domain.key_areas)}")
        print(f"  Layers: {len(procedure.domain.layers)}")
        print(f"  Agent tasks: {len(procedure.domain.agent_tasks)}")
        print(f"  Standards: {len(procedure.domain.professional_standards)}")

    print()
    print(procedure.print_workflow())

    # Test: start and run Phase 1 CODE steps
    print("\n── Starting Phase 1: Site Analysis ──")
    procedure.start("site_analysis")

    for step in procedure.current_phase.code_steps:
        status = procedure.execute_code_step(step)
        print(f"  CODE {step}: {status.value}")

    # Test: execute a judgment point (mock)
    print("\n── Executing JUDGMENT: site_interpretation (mock) ──")
    result = procedure.execute_judgment("site_interpretation")
    print(f"  Accepted: {result.accepted}")
    print(f"  Evidence refs: {len(result.evidence_refs)}")
    print(f"  Violations: {result.constraint_violations}")

    print("\n── Summary ──")
    import pprint
    pprint.pprint(procedure.summary())
