"""
Goal-Driven + Professional FSM Orchestrator for haidian Urban Design.

This is the autonomous agent loop. It drives the UrbanDesignProcedure state
machine, invokes LLM at JUDGMENT points with structured prompts, runs CODE
constraint checks at phase gates, and coordinates the Reflection Panel.

Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │ Orchestrator (this file)                                │
    │                                                        │
    │  procedure = UrbanDesignProcedure.from_repo()           │
    │  for phase in procedure.phases:                         │
    │    CODE steps (deterministic Python)                    │
    │    JUDGMENT points (LLM called with structured prompt)  │
    │    Phase gate (constraint engine validates exit)         │
    │                                                        │
    │  constraint_engine.validate() (all CODE constraints)    │
    │  reflection_panel.review() (7 LLM judges)               │
    │  → completed / retry / escalate                         │
    └─────────────────────────────────────────────────────────┘

Usage:
    python3 constraints/orchestrator.py --submission submissions/<login>/<slug>

The orchestrator works with any LLM backend. For Claude Code, it outputs
structured prompts that the surrounding agent picks up and feeds to the LLM.
"""

import json
import sys
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from enum import Enum

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
from constraints.engine import ConstraintEngine


# ── Orchestrator State ──────────────────────────────────────────


class LoopStatus(Enum):
    INIT = "init"
    PHASE_RUNNING = "phase_running"
    WAITING_FOR_LLM = "waiting_for_llm"
    CONSTRAINT_CHECKING = "constraint_checking"
    REFLECTION_PANEL = "reflection_panel"
    COMPLETED = "completed"
    ESCALATED = "escalated"


@dataclass
class LoopState:
    submission_path: str
    status: LoopStatus = LoopStatus.INIT
    current_phase: Optional[str] = None
    phase_attempt: int = 0
    total_iterations: int = 0
    max_iterations: int = 50
    stall_history: dict = field(default_factory=dict)
    constraint_results: dict = field(default_factory=dict)
    reflection_results: dict = field(default_factory=dict)
    started_at: str = ""
    log: list = field(default_factory=list)


@dataclass
class LLMGenerationRequest:
    """A structured request for the LLM to generate content for a phase."""
    phase: str
    phase_name: str
    prompt: str
    output_files: list[str]
    must_produce: list[str]
    must_not_produce: list[str]
    rollback_on_failure: str
    attempt: int
    max_retries: int


# ── Orchestrator ────────────────────────────────────────────────


class Orchestrator:
    """Autonomous orchestrator for Goal-Driven urban design generation.

    Drives the UrbanDesignProcedure state machine, invokes LLM at JUDGMENT
    points, runs CODE constraint checks, and coordinates the Reflection Panel.
    """

    def __init__(self, submission_path: str, repo_root: str = "."):
        self.submission_path = Path(submission_path)
        self.repo_root = Path(repo_root)
        self.procedure = UrbanDesignProcedure.from_repo(str(repo_root))
        self.procedure.submission_path = self.submission_path

        self.state = LoopState(
            submission_path=str(submission_path),
            started_at=datetime.now().isoformat(),
        )

        # Pluggable LLM callback: (JudgmentContext) → JudgmentResult
        self._llm_callback: Optional[Callable[[JudgmentContext], JudgmentResult]] = None

    def set_llm_callback(self, cb: Callable[[JudgmentContext], JudgmentResult]):
        """Set the LLM callback for JUDGMENT points."""
        self._llm_callback = cb

    # ── Main Loop ───────────────────────────────────────────

    def run(self) -> LoopState:
        """Execute the full Goal-Driven loop through all design phases.

        Stops at each JUDGMENT point waiting for LLM input (if no callback set),
        or runs autonomously if a callback is provided.
        """
        self.state.status = LoopStatus.PHASE_RUNNING
        self.procedure.start()

        while self.procedure.current_phase is not None:
            phase = self.procedure.current_phase
            self.state.current_phase = phase.phase_id
            self.state.phase_attempt = 0
            self._log(f"Starting phase: {phase.label_zh} ({phase.phase_id})")

            # ── Execute CODE steps ──
            for step_name in phase.code_steps:
                status = self.procedure.execute_code_step(step_name)
                self._log(f"  CODE {step_name}: {status.value}")
                if status == StepStatus.FAILED:
                    self._log(f"  WARNING: CODE step failed — will be caught at gate")

            # ── Execute JUDGMENT points ──
            for judgment_id in phase.judgment_points:
                self.state.status = LoopStatus.WAITING_FOR_LLM
                context = self.procedure._build_judgment_context(judgment_id, phase)

                if self._llm_callback:
                    result = self._llm_callback(context)
                    self.procedure.judgment_results.setdefault(phase.phase_id, []).append(result)
                    self._log(f"  JUDGMENT {judgment_id}: accepted={result.accepted}")
                else:
                    # No callback — output the prompt for external LLM
                    request = LLMGenerationRequest(
                        phase=phase.phase_id,
                        phase_name=phase.label_zh,
                        prompt=context.prompt_template,
                        output_files=[],  # Filled by what the phase produces
                        must_produce=[],
                        must_not_produce=[],
                        rollback_on_failure=phase.phase_id,
                        attempt=self.state.phase_attempt + 1,
                        max_retries=3,
                    )
                    self._save_llm_request(request)
                    self._log(f"  JUDGMENT {judgment_id}: prompt saved — waiting for LLM")
                    return self.state  # Stop here for external LLM

            # ── Advance to next phase via gate ──
            next_phase = self.procedure.advance()
            self.state.total_iterations += 1

            if next_phase.phase_id == "human_escalation":
                self.state.status = LoopStatus.ESCALATED
                self._log(f"ESCALATED: {next_phase.description}")
                return self.state

            if next_phase.phase_id == phase.phase_id:
                # Same phase — gate failed, retry
                self.state.phase_attempt += 1
                self._log(f"  Gate FAILED — retry {self.state.phase_attempt}")
                if self.state.phase_attempt >= 3:
                    self.state.status = LoopStatus.ESCALATED
                    self._log(f"ESCALATED: max retries exceeded for {phase.phase_id}")
                    return self.state
                continue

            # Check max iterations
            if self.state.total_iterations >= self.state.max_iterations:
                self.state.status = LoopStatus.ESCALATED
                self._log(f"ESCALATED: max iterations ({self.state.max_iterations}) exceeded")
                return self.state

        # ── All phases complete — run full constraint engine ──
        self.state.status = LoopStatus.CONSTRAINT_CHECKING
        self._log("All phases complete — running full constraint engine")
        constraint_ok = self._run_constraint_engine()
        self.state.constraint_results["all_pass"] = constraint_ok

        if not constraint_ok:
            self._log("Constraint engine found issues — returning for fixes")
            return self.state

        # ── Reflection Panel ──
        self.state.status = LoopStatus.REFLECTION_PANEL
        self._log("Constraint engine PASSED — ready for Reflection Panel")
        self._log("Run 7-judge panel: see review-panel/statutes.json")

        self.state.status = LoopStatus.COMPLETED
        return self.state

    def continue_after_llm(self, phase_id: str):
        """Called after LLM has produced content for a phase's JUDGMENT points.
        Continues the main loop from where it stopped.
        """
        self.state.status = LoopStatus.PHASE_RUNNING

        # Advance and continue
        next_phase = self.procedure.advance()
        self.state.total_iterations += 1

        if next_phase.phase_id == "human_escalation":
            self.state.status = LoopStatus.ESCALATED
            return self.state

        if next_phase.phase_id == phase_id:
            self.state.phase_attempt += 1

        # Resume the main loop
        return self._continue_loop()

    def _continue_loop(self) -> LoopState:
        """Continue the main loop from current phase."""
        # Simplified: re-enter run() which skips completed phases
        # by advancing through already-completed phases
        while self.procedure.current_phase is not None:
            phase = self.procedure.current_phase

            if phase.phase_id in self.procedure.completed_phases:
                self.procedure.advance()
                continue

            # Execute remaining steps for this phase
            for step_name in phase.code_steps:
                if step_name not in phase.step_results or phase.step_results[step_name] != StepStatus.PASSED:
                    self.procedure.execute_code_step(step_name)

            # JUDGMENT points
            for judgment_id in phase.judgment_points:
                self.state.status = LoopStatus.WAITING_FOR_LLM
                context = self.procedure._build_judgment_context(judgment_id, phase)
                if self._llm_callback:
                    result = self._llm_callback(context)
                else:
                    request = LLMGenerationRequest(
                        phase=phase.phase_id, phase_name=phase.label_zh,
                        prompt=context.prompt_template,
                        output_files=[], must_produce=[], must_not_produce=[],
                        rollback_on_failure=phase.phase_id,
                        attempt=self.state.phase_attempt + 1, max_retries=3,
                    )
                    self._save_llm_request(request)
                    return self.state

            next_phase = self.procedure.advance()
            self.state.total_iterations += 1

            if next_phase.phase_id == "human_escalation":
                self.state.status = LoopStatus.ESCALATED
                return self.state

        # All done
        self.state.status = LoopStatus.COMPLETED
        return self.state

    # ── Constraint Engine ───────────────────────────────────

    def _run_constraint_engine(self) -> bool:
        """Run the full constraint engine validation. Returns True if all pass."""
        try:
            engine = ConstraintEngine(self.repo_root)
            results = engine.validate(str(self.submission_path))
            failures = [r for r in results if not r.passed]
            self.state.constraint_results = {
                "total": len(results),
                "passed": len(results) - len(failures),
                "failed": len(failures),
                "failures": [
                    {"constraint_id": r.constraint_id, "detail": r.detail, "severity": r.severity}
                    for r in failures
                ],
            }
            return len(failures) == 0
        except Exception as e:
            self.state.constraint_results = {"error": str(e)}
            return False

    # ── Helpers ──────────────────────────────────────────────

    def _log(self, msg: str):
        self.state.log.append(f"[{datetime.now().isoformat()}] {msg}")
        print(msg)

    def _save_llm_request(self, request: LLMGenerationRequest):
        """Save LLM generation request to submission directory for external processing."""
        req_dir = self.submission_path / ".orchestrator"
        req_dir.mkdir(parents=True, exist_ok=True)
        req_file = req_dir / f"llm_request_{request.phase}.json"
        req_file.write_text(
            json.dumps({
                "phase": request.phase,
                "phase_name": request.phase_name,
                "prompt": request.prompt,
                "output_files": request.output_files,
                "must_produce": request.must_produce,
                "must_not_produce": request.must_not_produce,
                "attempt": request.attempt,
                "max_retries": request.max_retries,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Report ───────────────────────────────────────────────

    def status_report(self) -> dict:
        """Generate a machine-readable status report."""
        proc_summary = self.procedure.summary()
        return {
            "overall_status": self.state.status.value,
            "submission_path": self.state.submission_path,
            "current_phase": self.state.current_phase,
            "phase_attempt": self.state.phase_attempt,
            "total_iterations": self.state.total_iterations,
            "phases": proc_summary.get("phases", {}),
            "constraint_results": self.state.constraint_results,
            "started_at": self.state.started_at,
            "log": self.state.log[-20:],  # Last 20 entries
        }


# ── CLI ─────────────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Goal-Driven Orchestrator for haidian Urban Design"
    )
    parser.add_argument("--submission", required=True,
                        help="Path to submission directory")
    parser.add_argument("--repo-root", default=".",
                        help="Path to haidian repo root")
    parser.add_argument("--continue-after", metavar="PHASE_ID",
                        help="Continue after LLM generation for PHASE_ID")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON status report")
    args = parser.parse_args()

    orch = Orchestrator(
        submission_path=args.submission,
        repo_root=args.repo_root,
    )

    if args.continue_after:
        result = orch.continue_after_llm(args.continue_after)
    else:
        result = orch.run()

    if args.json:
        print(json.dumps(orch.status_report(), indent=2, ensure_ascii=False))
    else:
        report = orch.status_report()
        print(f"\n{'='*60}")
        print(f"Orchestrator Status: {report['overall_status']}")
        print(f"Phase: {report['current_phase']}")
        print(f"Iterations: {report['total_iterations']}")
        print(f"{'='*60}")
        phases = report.get('phases', {})
        for pid, ps in phases.items():
            status = ps.get('status', 'pending')
            icon = "✓" if status == "completed" else "●" if status == "running" else "○"
            print(f"  {icon} {pid} ({ps.get('label_zh', '')}): {status}")

        if report.get('constraint_results'):
            cr = report['constraint_results']
            if isinstance(cr, dict):
                print(f"\nConstraints: {cr.get('passed', '?')}/{cr.get('total', '?')} passed")


if __name__ == "__main__":
    main()
