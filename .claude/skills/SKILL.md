---
name: goal-driven
description: Start an autonomous improvement loop. Give me a verifier command and I iterate until it passes.
argument-hint: "<verifier> [--allow <path>]... [--forbid <path>]..."
---

# Goal-Driven Skill

User says: `/goal-driven "pytest" --allow src/ --allow tests/ --forbid config/`

You start an autonomous improvement loop.

## Phase 1: Gather (if missing)

If the user didn't provide all info, ask ONLY these questions:

1. "How do I verify success?" (e.g. `pytest`, `npx tsc --noEmit`, `./check.sh`)
2. "What can I modify?" (e.g. `src/`, `tests/`)
3. "What must I never touch?" (e.g. `config/`, `.github/`)

Do NOT ask anything else. Default answers if user says "just go":
- verifier: `pytest -q 2>&1 | grep -oP '\d+ failed' || echo "0"`
- allow: `src/`, `tests/`
- forbid: `package.json`, `.github/`

## Phase 2: Baseline

Run the verifier. Record the number. This is the baseline.

## Phase 3: Loop (NEVER STOP)

```
WHILE verifier != 0:
    1. Look at verifier output — what's failing?
    2. Look at git log -3 — what did we already try?
    3. Pick ONE failure. Make the SMALLEST possible fix.
    4. Edit the file(s).
    5. Run verifier.
    6. IF number went down:
         git add -A && git commit -m "fix: <what changed>"
         Log to results.tsv: keep
       ELSE:
         git checkout .  (discard)
         Log to results.tsv: discard
    7. If 5 consecutive discards: try a DIFFERENT approach.
       Do NOT ask the user. Think harder.
```

## Rules

- **NEVER ASK "should I continue?"** — you keep going until verifier=0.
- **ONE change per iteration** — smallest possible. Not a refactor, not a rewrite.
- **Git is memory** — each commit is one hypothesis tested.
- **When stuck** — read error messages more carefully, read the code, try a different angle.
- **Simplicity wins** — a fix that deletes code is better than a fix that adds code.

## Phase 4: Done

When verifier = 0:
- Print summary: iterations, keeps, discards, final git log
- Say "Done. Verifier passed. Check git log for the chain of fixes."
