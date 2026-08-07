"""Urban Design Constraint System + Professional State Machine for haidian.

CANONICAL ARCHITECTURE (single stack, no duplicates):

  domain.py       — Professional urban design domain model (types, concepts)
  procedure.py    — UrbanDesignProcedure: THE state machine (6 phases, CODE/JUDGMENT)
  engine.py       — ConstraintEngine: deterministic CODE checks (zero LLM)
  extractors.py   — ConstraintExtractor: auto-extract constraints from repo files
  orchestrator.py — Goal-Driven orchestrator (drives procedure + engine + reflection)
  registry.json   — Constraint registry extracted from repo physical files

Architecture principle (from user):
  "Constraints are hard-coded or state machines. LLM is used locally under rules."
  — State machine controls ALL flow. LLM called ONLY at JUDGMENT points.
  — Never does the LLM decide what happens next.

Entry points:
  python3 constraints/orchestrator.py --submission <path>      # Full pipeline
  python3 -m constraints.procedure                              # State machine demo
  python3 -m constraints.engine                                 # Constraint validation
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
