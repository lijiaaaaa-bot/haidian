# Archived goal-driven / FSM paths

These files are **deprecated** and kept for reference or opt-in legacy runs.

## Canonical autoresearch (use this)

- Protocol: [`program.md`](../program.md)
- Evaluator: [`scripts/acceptance.py`](../scripts/acceptance.py)
- Cursor / Cloud Agent: read `program.md`, run acceptance, commit one fix per round

## Archived contents

| Path | Was | Legacy run |
|---|---|---|
| `archive/run_pipeline.py` | 6-phase FSM entry | `HAIDIAN_LEGACY_FSM=1 python3 run_pipeline.py --submission …` |
| `archive/constraints/procedure.py` | `UrbanDesignProcedure` state machine | imported via `constraints/procedure.py` shim (emits `DeprecationWarning`) |
| `scripts/goal_driven_loop.py` | ~2600-line MLX/Ollama master loop | `HAIDIAN_LEGACY_LOOP=1 bash scripts/run_autonomous.sh` |

## Why archived

- Three parallel pipelines (skills/PR, monolith loop, FSM) caused doc drift and false “progress” when the verifier could not fail.
- `acceptance.py` unifies CODE + content floors + self_check into one `FAILURES N` metric.
- Cloud Agent and Cursor do not need macOS MLX paths or infinite restart supervisors.

Domain assets (`constraints/engine.py`, `brief/`, `review-panel/`) remain active and are **not** archived.
