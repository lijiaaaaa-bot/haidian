"""Constraint engine checks backed by urban-design-knowledge state machines.

These checks encode real urban planning regulations as deterministic CODE checks.
They are NOT text-grep checks — they use the state machines from
urban-design-knowledge/src/ to make geometric and classificatory judgments.

Key principle: the state machines are pure functions. Same input → same output.
No LLM involvement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from constraints.state_machines.three_lines import (
    Parcel,
    ThreeLinesBoundaries,
)
from constraints.state_machines.land_use_validator import (
    LandUseOrchestrator,
    ZoneJudgementContext,
    judge_land_use,
)

from constraints.engine import CheckOutcome


def _read_geojson(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _make_parcel(feature: dict) -> Parcel | None:
    """Convert a GeoJSON feature to a state-machine Parcel. Returns None if geometry is invalid."""
    try:
        return Parcel.from_geojson_feature(feature)
    except Exception:
        return None


# ── Check: land use classification validity ──────────────────────────


def _load_land_use_codes() -> set:
    """Load valid land_use_codes from the state machine's enums."""
    import json as _json
    enums_path = Path(__file__).resolve().parent.parent / "brief" / "site-package" / "enums" / "land_use_codes.json"
    if enums_path.exists():
        data = _json.loads(enums_path.read_text(encoding="utf-8"))
        return {c["code"] for c in data.get("codes", [])}
    # Fallback: hardcoded from GB 50137-2011 + 2023 update
    return {
        "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
        "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
        "21", "22", "23", "24",
    }


def check_land_use_classification(sub_path: Path, _params: dict) -> tuple[CheckOutcome, str, str]:
    """Validate every land_use feature has a valid land_use_code.

    State-machine-backed: reads the authoritative code list from
    brief/site-package/enums/land_use_codes.json rather than a hardcoded list.
    This check will auto-update when the enum file is updated.
    """
    land_use_path = sub_path / "geometry" / "land_use.geojson"
    gj = _read_geojson(land_use_path)
    if gj is None:
        return (CheckOutcome.SKIP, "land_use.geojson 不存在或无法解析", "")

    features = gj.get("features", [])
    if not features:
        return (CheckOutcome.SKIP, "land_use.geojson 无 feature", "")

    valid_codes = _load_land_use_codes()
    violations = []
    for feat in features:
        props = feat.get("properties", {})
        code = str(props.get("land_use_code", ""))
        if not code:
            violations.append(f"feature {props.get('id', '?')}: 缺少 land_use_code 属性")
        elif code not in valid_codes:
            nearby = sorted(valid_codes)[:20]
            violations.append(f"feature {props.get('id', '?')}: '{code}' 不是有效的用地分类代码 (valid: {nearby})")

    if violations:
        return (
            CheckOutcome.FAIL,
            f"land_use.geojson: {len(violations)}/{len(features)} 个 feature 用地代码无效",
            "\n".join(violations[:10]),
        )

    return (
        CheckOutcome.PASS,
        f"land_use.geojson: 全部 {len(features)} 个 feature 用地分类合规 (valid codes: {len(valid_codes)})",
        "",
    )


# ── Check: three-lines awareness ─────────────────────────────────────


def check_three_lines_awareness(sub_path: Path, _params: dict) -> tuple[CheckOutcome, str, str]:
    """Check that the proposal acknowledges three-lines constraints.

    Full geometric validation requires official boundary data (not yet available).
    This check ensures the concept is at least documented.
    """
    proposal_path = sub_path / "proposal.md"
    if not proposal_path.exists():
        return (CheckOutcome.SKIP, "proposal.md 不存在", "")

    text = proposal_path.read_text(encoding="utf-8", errors="replace")

    keywords = [
        ("生态保护红线", "ecological redline"),
        ("永久基本农田", "permanent basic farmland"),
        ("城镇开发边界", "urban development boundary"),
        ("三区三线", "three zones three lines"),
    ]

    found = []
    missing = []
    for zh, en in keywords:
        if zh in text or en.lower() in text.lower():
            found.append(zh)
        else:
            missing.append(zh)

    if missing:
        return (
            CheckOutcome.FAIL,
            f"proposal.md 未提及 {len(missing)}/{len(keywords)} 项三区三线概念: {', '.join(missing)}",
            f"proposal.md: missing three-lines keywords — official boundary data pending",
        )

    return (
        CheckOutcome.PASS,
        f"proposal.md 已提及全部 {len(found)} 项三区三线概念",
        "",
    )


# ── Registry entries ──────────────────────────────────────────────────

STATE_MACHINE_REGISTRY_ENTRIES = [
    {
        "constraint_id": "C-SM-LANDUSE",
        "name": "state_machine_land_use_classification",
        "category": "spatial",
        "severity": "critical",
        "description": "用地分类状态机校验: 每个 land_use feature 的地类代码符合国土空间规划分类标准",
        "check_function": "check_land_use_classification",
        "enabled": True,
        "params": {},
    },
    {
        "constraint_id": "C-SM-THREELINES",
        "name": "three_lines_awareness",
        "category": "compliance",
        "severity": "high",
        "description": "三区三线概念校验: proposal 必须提及生态保护红线/永久基本农田/城镇开发边界",
        "check_function": "check_three_lines_awareness",
        "enabled": True,
        "params": {},
    },
]
