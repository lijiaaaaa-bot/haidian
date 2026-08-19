"""Urban Design Constraint System for haidian.

CANONICAL autoresearch (2026-08-19):

  program.md          — lightweight agent protocol (Cursor / Cloud Agent)
  scripts/acceptance.py — unified evaluator (CODE + content + self_check)
  scripts/goal_verifier.py — thin wrapper (--code-only for legacy)

Active domain modules:

  domain.py       — Professional urban design domain model (types, concepts)
  engine.py       — ConstraintEngine: deterministic CODE checks (zero LLM)
  extractors.py   — ConstraintExtractor: auto-extract constraints from repo files
  registry.json   — Constraint registry extracted from repo physical files

Deprecated / archived (see archive/README.md):

  procedure.py    — UrbanDesignProcedure FSM (shim → archive/constraints/)
  orchestrator.py — FSM orchestrator (legacy)
  run_pipeline.py — FSM entry (shim → archive/run_pipeline.py or acceptance.py)
  scripts/goal_driven_loop.py — MLX monolith (HAIDIAN_LEGACY_LOOP=1)

Architecture principle:
  "Constraints are hard-coded or state machines. LLM is used locally under rules."
  — For autoresearch, the agent reads failures from acceptance.py and fixes one item per round.

Entry points:
  python3 scripts/acceptance.py --submission <path>           # Canonical evaluator
  bash scripts/run_autonomous.sh                              # Single acceptance run + hints
  HAIDIAN_LEGACY_FSM=1 python3 run_pipeline.py --submission … # Archived FSM
  python3 -m constraints.engine                              # Constraint validation only
"""

from constraints.engine import ConstraintEngine, ConstraintResult, CheckOutcome
from constraints.extractors import ConstraintExtractor
from constraints.domain import (
    UrbanDesignDomain,
    CoordinateSystem,
    ScopeLevel,
    ScopeDefinition,
    KeyAreaDefinition,
    LayerDefinition,
    LayerRole,
    LandUseCode,
    PlanningLimit,
    ProfessionalStandard,
    BoundaryClause,
    AgentTask,
    RequiredFile,
)
from constraints.procedure import (
    UrbanDesignProcedure,
    DesignPhase,
    StepKind,
    StepStatus,
    JudgmentContext,
    JudgmentResult,
    PhaseGateResult,
    StallDetector,
)

__all__ = [
    # Constraint Engine
    "ConstraintEngine", "ConstraintResult", "CheckOutcome", "ConstraintExtractor",
    # Domain Model (professional concepts)
    "UrbanDesignDomain", "CoordinateSystem", "ScopeLevel", "ScopeDefinition",
    "KeyAreaDefinition", "LayerDefinition", "LayerRole", "LandUseCode",
    "PlanningLimit", "ProfessionalStandard", "BoundaryClause", "AgentTask",
    "RequiredFile",
    # Procedure (state machine — canonical)
    "UrbanDesignProcedure", "DesignPhase", "StepKind", "StepStatus",
    "JudgmentContext", "JudgmentResult", "PhaseGateResult", "StallDetector",
]
