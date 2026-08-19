"""DEPRECATED — 6-phase UrbanDesignProcedure FSM (archived).

Canonical autoresearch loop: ``program.md`` + ``scripts/acceptance.py``.
Legacy copy lives in ``archive/constraints/procedure.py``.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "constraints.procedure is deprecated. Use program.md + scripts/acceptance.py "
    "for autoresearch; the FSM is archived under archive/constraints/.",
    DeprecationWarning,
    stacklevel=2,
)

from archive.constraints.procedure import *  # noqa: F403
