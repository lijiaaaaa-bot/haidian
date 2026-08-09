"""Hard Constraint Engine — deterministic, zero-LLM validation.

Architecture (mirrors Grok Build's goal_classifier):
  - Loads Constraint Registry (data, not code)
  - For each enabled CODE constraint, runs the corresponding check function
  - Returns structured results — no LLM involved
  - Only LLM constraints are deferred to the Reflection Panel

The Goal-Driven loop feeds off these results: precise failures → targeted repairs.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class CheckOutcome(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"


@dataclass
class ConstraintResult:
    """Single constraint check result — the atom of the validation system."""

    constraint_id: str
    name: str
    outcome: CheckOutcome
    severity: str  # critical | high | medium
    category: str  # spatial | textual | metric | package | compliance
    detail: str = ""
    evidence: str = ""  # concrete location + snippet, like hardlaw's EvidenceRef
    check_type: str = "CODE"
    elapsed_ms: float = 0.0

    @property
    def is_pass(self) -> bool:
        return self.outcome == CheckOutcome.PASS

    @property
    def is_critical_fail(self) -> bool:
        return self.outcome == CheckOutcome.FAIL and self.severity == "critical"

    @property
    def fingerprint(self) -> str:
        """Stable fingerprint for stall detection (mirrors Grok Build's gap_fingerprint)."""
        token = f"{self.constraint_id}:{self.detail}"
        return hashlib.sha256(token.encode()).hexdigest()[:16]


class ConstraintEngine:
    """Deterministic constraint validator.

    Usage:
        engine = ConstraintEngine(repo_root="/path/to/haidian")
        engine.load_registry()  # loads registry.json
        results = engine.validate("submissions/lijiaaaaa-bot/my-proposal")
        # results is a list of ConstraintResult

        engine.report(results)  # prints summary
    """

    def __init__(self, repo_root: str | Path = "."):
        self.root = Path(repo_root)
        self.registry: dict[str, Any] = {}
        self.constraints: list[dict] = []
        self.overrides: list[dict] = []

        # Register built-in CODE check functions
        self._checkers: dict[str, Callable] = {}

    # ── Registry Loading ────────────────────────────────────────────

    def load_registry(self, path: str | Path | None = None) -> None:
        """Load constraint registry from JSON file."""
        if path is None:
            path = self.root / "constraints" / "registry.json"

        registry_path = Path(path)
        if not registry_path.exists():
            raise FileNotFoundError(
                f"Constraint registry not found: {registry_path}\n"
                "Run: python3 constraints/extractors.py --generate"
            )

        self.registry = json.loads(registry_path.read_text(encoding="utf-8"))
        self.constraints = self.registry.get("constraints", [])
        self.overrides = self.registry.get("manual_overrides", [])

        # Merge overrides
        override_map = {o["constraint_id"]: o for o in self.overrides}
        for i, c in enumerate(self.constraints):
            cid = c.get("constraint_id", "")
            if cid in override_map:
                for key, val in override_map[cid].items():
                    if key != "constraint_id":
                        c[key] = val

    def add_constraint(self, constraint: dict) -> None:
        """Dynamically add a constraint at runtime."""
        self.constraints.append(constraint)

    def disable_constraint(self, constraint_id: str) -> None:
        """Dynamically disable a constraint."""
        for c in self.constraints:
            if c.get("constraint_id") == constraint_id:
                c["enabled"] = False
                return

    def enable_constraint(self, constraint_id: str) -> None:
        """Dynamically enable a constraint."""
        for c in self.constraints:
            if c.get("constraint_id") == constraint_id:
                c["enabled"] = True
                return

    # ── Validation ──────────────────────────────────────────────────

    def validate(self, submission_path: str | Path) -> list[ConstraintResult]:
        """Run all enabled CODE constraints against a submission.

        LLM constraints are skipped — they go to the Reflection Panel.
        """
        sub_path = self.root / Path(submission_path)
        results: list[ConstraintResult] = []

        enabled_code_constraints = [
            c for c in self.constraints
            if c.get("enabled", True) and c.get("check_type") == "CODE"
        ]

        for constraint in enabled_code_constraints:
            cid = constraint.get("constraint_id", "unknown")
            check_fn_name = constraint.get("check_function", "")
            check_fn = self._get_checker(check_fn_name)

            if check_fn is None:
                results.append(ConstraintResult(
                    constraint_id=cid,
                    name=constraint.get("name", cid),
                    outcome=CheckOutcome.SKIP,
                    severity=constraint.get("severity", "medium"),
                    category=constraint.get("category", "unknown"),
                    detail=f"No checker registered for '{check_fn_name}'",
                    check_type="CODE",
                ))
                continue

            try:
                import time
                t0 = time.monotonic()
                outcome, detail, evidence = check_fn(sub_path, constraint.get("params", {}))
                elapsed = (time.monotonic() - t0) * 1000

                results.append(ConstraintResult(
                    constraint_id=cid,
                    name=constraint.get("name", cid),
                    outcome=outcome,
                    severity=constraint.get("severity", "medium"),
                    category=constraint.get("category", "unknown"),
                    detail=detail,
                    evidence=evidence,
                    check_type="CODE",
                    elapsed_ms=elapsed,
                ))
            except Exception as e:
                results.append(ConstraintResult(
                    constraint_id=cid,
                    name=constraint.get("name", cid),
                    outcome=CheckOutcome.ERROR,
                    severity=constraint.get("severity", "medium"),
                    category=constraint.get("category", "unknown"),
                    detail=f"Checker error: {e}",
                    check_type="CODE",
                ))

        return results

    def _get_checker(self, name: str):
        """Resolve a check function by name from built-in registry."""
        if not self._checkers:
            self._register_builtins()
        return self._checkers.get(name)

    def _register_builtins(self) -> None:
        """Register all built-in CODE check functions."""
        self._checkers.update({
            "verify_required_layers": _check_required_layers,
            "verify_features_within_boundary": _check_features_within_boundary,
            "verify_land_use_coverage": _check_land_use_coverage,
            "verify_no_land_use_overlap": _check_no_land_use_overlap,
            "verify_area_tolerance": _check_area_tolerance,
            "verify_provisional_marking": _check_provisional_marking,
            "verify_task_coverage": _check_task_coverage,
            "grep_forbidden_patterns": _check_forbidden_patterns,
            "verify_required_wording": _check_required_wording,
            "verify_missing_controls_documented": _check_missing_controls_documented,
            "verify_source_authority": _check_source_authority,
            "verify_sanity_bounds": _check_sanity_bounds,
            "verify_enum_values": _check_enum_values,
            "verify_crs_used": _check_crs_used,
            "verify_locked_layers": _check_locked_layers,
            "verify_layer_names": _check_layer_names,
        })

    # ── Reporting ───────────────────────────────────────────────────

    def report(self, results: list[ConstraintResult]) -> dict:
        """Produce a summary report consumable by the Goal-Driven loop."""
        passed = [r for r in results if r.is_pass]
        failed = [r for r in results if r.outcome == CheckOutcome.FAIL]
        critical = [r for r in failed if r.is_critical_fail]
        skipped = [r for r in results if r.outcome == CheckOutcome.SKIP]
        errors = [r for r in results if r.outcome == CheckOutcome.ERROR]

        return {
            "total": len(results),
            "passed": len(passed),
            "failed": len(failed),
            "critical_failures": len(critical),
            "skipped": len(skipped),
            "errors": len(errors),
            "all_code_checks_pass": len(failed) == 0,
            "ready_for_llm_review": len(critical) == 0,
            "failures_by_category": self._group_by(failed, "category"),
            "failures_by_severity": self._group_by(failed, "severity"),
            "results": [
                {
                    "constraint_id": r.constraint_id,
                    "name": r.name,
                    "outcome": r.outcome.value,
                    "severity": r.severity,
                    "category": r.category,
                    "detail": r.detail,
                    "evidence": r.evidence,
                }
                for r in results
            ],
        }

    def stall_check(self, current: list[ConstraintResult], previous: list[ConstraintResult]) -> bool:
        """Check if the same failures appear in two consecutive runs (stall detection)."""
        current_failures = {r.fingerprint for r in current if r.outcome == CheckOutcome.FAIL}
        previous_failures = {r.fingerprint for r in previous if r.outcome == CheckOutcome.FAIL}
        return bool(current_failures and current_failures == previous_failures)

    @staticmethod
    def _group_by(results: list[ConstraintResult], key: str) -> dict:
        groups: dict[str, int] = {}
        for r in results:
            k = getattr(r, key, "unknown")
            groups[k] = groups.get(k, 0) + 1
        return groups


# ═══════════════════════════════════════════════════════════════════════
# Built-in CODE Check Functions
#
# Each function:
#   Input:  submission_path (Path), params (dict)
#   Output: (CheckOutcome, detail: str, evidence: str)
#
# These are PURE — no LLM, no randomness, same input → same output.
# ═══════════════════════════════════════════════════════════════════════

def _check_required_layers(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Verify all required GeoJSON layers exist."""
    required = params.get("required_layers", [])
    geometry_dir = sub_path / "geometry"
    missing = []
    for layer in required:
        # Map layer name to expected filename
        filename = f"{layer.lower()}.geojson"
        if not (geometry_dir / filename).exists():
            missing.append(layer)

    if missing:
        return (
            CheckOutcome.FAIL,
            f"缺失 {len(missing)} 个必交图层: {', '.join(missing)}",
            f"geometry/: missing {missing}",
        )
    return (CheckOutcome.PASS, f"全部 {len(required)} 个必交图层存在", "")


def _check_features_within_boundary(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check all generated features are within site_boundary."""
    try:
        from shapely.geometry import shape
        from shapely import from_geojson
    except ImportError:
        return (CheckOutcome.SKIP, "shapely not available", "")

    boundary_file = sub_path / "geometry" / "site_boundary.geojson"
    if not boundary_file.exists():
        return (CheckOutcome.FAIL, "site_boundary.geojson 不存在", str(boundary_file))

    boundary_data = json.loads(boundary_file.read_text(encoding="utf-8"))
    boundaries = []
    for f in boundary_data.get("features", []):
        geom = f.get("geometry")
        if geom:
            boundaries.append(shape(geom))

    if not boundaries:
        return (CheckOutcome.FAIL, "site_boundary 无有效 geometry", "")

    # Union all boundary polygons
    site = boundaries[0]
    for b in boundaries[1:]:
        site = site.union(b)

    # Check each generated layer
    generated_layers = params.get("generated_layers", [])
    violations = []
    for layer_name in generated_layers:
        layer_file = sub_path / "geometry" / f"{layer_name.lower()}.geojson"
        if not layer_file.exists():
            continue
        layer_data = json.loads(layer_file.read_text(encoding="utf-8"))
        for feat in layer_data.get("features", []):
            geom = feat.get("geometry")
            if not geom:
                continue
            try:
                g = shape(geom)
                if not site.contains(g):
                    feat_id = feat.get("properties", {}).get("id", feat.get("id", "?"))
                    violations.append(f"{layer_name}/{feat_id}")
            except Exception:
                pass

    if violations:
        return (
            CheckOutcome.FAIL,
            f"{len(violations)} 个 feature 超出 site_boundary: {', '.join(violations[:10])}",
            f"geometry/: out-of-bound features: {violations[:10]}",
        )
    return (CheckOutcome.PASS, "所有 feature 在 site_boundary 内", "")


def _check_land_use_coverage(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check land_use.geojson covers the full site_boundary without gaps."""
    try:
        from shapely.geometry import shape
    except ImportError:
        return (CheckOutcome.SKIP, "shapely not available", "")

    boundary_file = sub_path / "geometry" / "site_boundary.geojson"
    landuse_file = sub_path / "geometry" / "land_use.geojson"

    if not boundary_file.exists() or not landuse_file.exists():
        return (CheckOutcome.SKIP, "site_boundary 或 land_use 文件不存在", "")

    boundary_data = json.loads(boundary_file.read_text(encoding="utf-8"))
    landuse_data = json.loads(landuse_file.read_text(encoding="utf-8"))

    # Build site boundary
    site_polys = [shape(f["geometry"]) for f in boundary_data.get("features", []) if f.get("geometry")]
    if not site_polys:
        return (CheckOutcome.FAIL, "site_boundary 无有效 geometry", "")

    site = site_polys[0]
    for p in site_polys[1:]:
        site = site.union(p)

    # Union all land use polygons
    lu_polys = []
    for f in landuse_data.get("features", []):
        geom = f.get("geometry")
        if geom:
            try:
                lu_polys.append(shape(geom))
            except Exception:
                pass

    if not lu_polys:
        return (CheckOutcome.FAIL, "land_use.geojson 无有效 polygon", "")

    lu_union = lu_polys[0]
    for p in lu_polys[1:]:
        lu_union = lu_union.union(p)

    # Check coverage
    gap = site.difference(lu_union)
    if gap.is_empty or gap.area < 1.0:  # < 1 sqm = acceptable
        return (CheckOutcome.PASS, "land_use 完全覆盖 site_boundary，无间隙", "")

    gap_pct = (gap.area / site.area) * 100
    return (
        CheckOutcome.FAIL,
        f"land_use 未完全覆盖 site_boundary: 间隙面积约 {gap.area:.0f} m² ({gap_pct:.1f}%)",
        f"geometry/land_use.geojson: gap area {gap.area:.0f} m²",
    )


def _check_no_land_use_overlap(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check no overlapping land_use polygons."""
    try:
        from shapely.geometry import shape
    except ImportError:
        return (CheckOutcome.SKIP, "shapely not available", "")

    landuse_file = sub_path / "geometry" / "land_use.geojson"
    if not landuse_file.exists():
        return (CheckOutcome.SKIP, "land_use.geojson 不存在", "")

    landuse_data = json.loads(landuse_file.read_text(encoding="utf-8"))
    features = landuse_data.get("features", [])
    polys = []
    for f in features:
        geom = f.get("geometry")
        if geom:
            try:
                polys.append((f.get("properties", {}).get("id", "?"), shape(geom)))
            except Exception:
                pass

    overlaps = []
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            id_i, p_i = polys[i]
            id_j, p_j = polys[j]
            intersection = p_i.intersection(p_j)
            if not intersection.is_empty and intersection.area > 1.0:
                overlaps.append(f"{id_i} ∩ {id_j}")

    if overlaps:
        return (
            CheckOutcome.FAIL,
            f"land_use 存在 {len(overlaps)} 处重叠: {', '.join(overlaps[:5])}",
            f"geometry/land_use.geojson: overlaps {overlaps[:5]}",
        )
    return (CheckOutcome.PASS, "land_use 无重叠", "")


def _check_area_tolerance(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check area within tolerance of declared value."""
    declared = params.get("declared_area_sqm")
    tolerance_pct = params.get("tolerance_pct", 5.0)
    scope_label = params.get("scope_label", "unknown")
    metric_key = params.get("metric_key", None)

    if declared is None:
        return (CheckOutcome.SKIP, "无 declared area 参数", "")

    # Read metrics.json to find the actual area
    metrics_file = sub_path / "metrics.json"
    if not metrics_file.exists():
        return (CheckOutcome.SKIP, "metrics.json 不存在，无法验证面积", "")

    try:
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return (CheckOutcome.FAIL, "metrics.json 不是合法 JSON", str(metrics_file))

    # Find the matching metric
    actual = None
    
    # If a specific metric_key is provided, try top-level first, then nested metrics.{key}.value
    if metric_key and isinstance(metrics, dict):
        actual = metrics.get(metric_key)
        # Also try nested structure: metrics.metrics.{metric_key}.value
        if actual is None and isinstance(metrics.get("metrics"), dict):
            metric_entry = metrics["metrics"].get(metric_key)
            if isinstance(metric_entry, dict):
                actual = metric_entry.get("value")
    
    # Fallback: scan for first _sqm key at top level
    if actual is None:
        for m in metrics if isinstance(metrics, list) else [metrics]:
            if isinstance(m, dict):
                for key, val in m.items():
                    if isinstance(val, (int, float)) and key.endswith("_sqm"):
                        actual = val
                        break
    
    # Fallback: scan nested metrics.{key}.value for _sqm keys
    if actual is None and isinstance(metrics, dict) and isinstance(metrics.get("metrics"), dict):
        for key, entry in metrics["metrics"].items():
            if isinstance(entry, dict) and key.endswith("_sqm"):
                val = entry.get("value")
                if isinstance(val, (int, float)):
                    actual = val
                    break

    if actual is None and isinstance(metrics, dict):
        actual = metrics.get("site_area_sqm")
        # Try nested
        if actual is None and isinstance(metrics.get("metrics"), dict):
            entry = metrics["metrics"].get("site_area_sqm")
            if isinstance(entry, dict):
                actual = entry.get("value")

    if actual is None:
        return (CheckOutcome.FAIL, f"metrics.json 中未找到面积值", str(metrics_file))

    delta_pct = abs(actual - declared) / declared * 100
    if delta_pct <= tolerance_pct:
        return (
            CheckOutcome.PASS,
            f"{scope_label} 面积 {actual:.0f} m² 在公告值 {declared:,} m² 的 {tolerance_pct}% 容差内 (偏差 {delta_pct:.1f}%)",
            "",
        )

    return (
        CheckOutcome.FAIL,
        f"{scope_label} 面积 {actual:.0f} m² 超出公告值 {declared:,} m² 的 {tolerance_pct}% 容差 (偏差 {delta_pct:.1f}%)",
        f"metrics.json: {metric_key or 'site_area_sqm'}={actual}, declared={declared}, delta={delta_pct:.1f}%",
    )


def _check_provisional_marking(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check provisional boundary is properly marked."""
    required_role = params.get("geometry_role", "provisional_constraint")
    official_boundary = params.get("official_boundary", False)

    geometry_dir = sub_path / "geometry"
    for geojson_file in geometry_dir.glob("*.geojson"):
        data = json.loads(geojson_file.read_text(encoding="utf-8"))
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            if props.get("geometry_role") == "provisional_constraint":
                # Must have official_boundary=false
                if props.get("official_boundary") != False:
                    feat_id = props.get("id", "?")
                    return (
                        CheckOutcome.FAIL,
                        f"Feature {feat_id}: provisional geometry 标记为 official_boundary=true",
                        f"{geojson_file.name}#{feat_id}: official_boundary should be false",
                    )
                # Must have boundary_precision
                if not props.get("boundary_precision"):
                    feat_id = props.get("id", "?")
                    return (
                        CheckOutcome.FAIL,
                        f"Feature {feat_id}: provisional geometry 缺少 boundary_precision 字段",
                        f"{geojson_file.name}#{feat_id}: missing boundary_precision",
                    )

    return (CheckOutcome.PASS, "所有 provisional boundary 标记正确", "")


def _check_task_coverage(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check compliance_matrix covers a specific task."""
    req_id = params.get("requirement_id", "")
    title = params.get("title_zh", req_id)

    matrix_file = sub_path / "compliance_matrix.json"
    if not matrix_file.exists():
        return (CheckOutcome.FAIL, "compliance_matrix.json 不存在", str(matrix_file))

    try:
        matrix = json.loads(matrix_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return (CheckOutcome.FAIL, "compliance_matrix.json 不是合法 JSON", str(matrix_file))

    # Search for the requirement
    entries = matrix if isinstance(matrix, list) else matrix.get("entries", [])
    for entry in entries:
        if entry.get("requirement_id") == req_id:
            # Check evidence fields are non-empty
            report_sections = entry.get("report_sections", [])
            geojson_layers = entry.get("geojson_layers", [])
            if not report_sections and not geojson_layers:
                return (
                    CheckOutcome.FAIL,
                    f"{title} ({req_id}): 在 compliance_matrix 中存在但无任何 evidence 引用",
                    f"compliance_matrix.json: {req_id} has empty evidence",
                )
            return (
                CheckOutcome.PASS,
                f"{title} ({req_id}): 已覆盖",
                "",
            )

    return (
        CheckOutcome.FAIL,
        f"{title} ({req_id}): 在 compliance_matrix.json 中缺失",
        f"compliance_matrix.json: missing requirement {req_id}",
    )


def _check_forbidden_patterns(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Grep proposal.md for forbidden text patterns — zero LLM."""
    forbidden = params.get("forbidden_patterns", [])
    target_file_name = params.get("target_file", "proposal.md")
    target_file = sub_path / target_file_name

    if not target_file.exists():
        return (CheckOutcome.FAIL, f"{target_file_name} 不存在", str(target_file))

    text = target_file.read_text(encoding="utf-8")
    hits = []
    for pattern in forbidden:
        # Pattern might be a keyword or a more complex phrase
        # Extract core keyword from descriptive phrases like "控规调整、容积率..."
        for keyword in re.split(r'[、，,]', pattern):
            keyword = keyword.strip()
            if not keyword:
                continue
            if keyword in text:
                # Find context
                idx = text.find(keyword)
                start = max(0, idx - 20)
                end = min(len(text), idx + len(keyword) + 30)
                context = text[start:end].replace("\n", " ").strip()
                hits.append(f"'{keyword}' → ...{context}...")

    if hits:
        return (
            CheckOutcome.FAIL,
            f"proposal.md 中发现 {len(hits)} 处禁止性声明",
            "\n".join(hits[:5]),
        )
    return (CheckOutcome.PASS, "未发现禁止性声明", "")


def _check_required_wording(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check proposal.md contains required phrasing."""
    phrases = params.get("required_phrases", [])
    target_file_name = params.get("target_file", "proposal.md")
    target_file = sub_path / target_file_name

    if not target_file.exists():
        return (CheckOutcome.FAIL, f"{target_file_name} 不存在", str(target_file))

    text = target_file.read_text(encoding="utf-8")
    missing = [p for p in phrases if p not in text]
    found = [p for p in phrases if p in text]

    if missing:
        return (
            CheckOutcome.FAIL,
            f"缺少强制措辞: {', '.join(missing)} (已出现: {', '.join(found) if found else '无'})",
            f"{target_file_name}: missing required wording: {missing}",
        )
    return (CheckOutcome.PASS, f"全部 {len(phrases)} 条强制措辞已出现", "")


def _check_missing_controls_documented(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check that missing regulatory controls are documented in assumptions.json."""
    missing_controls = params.get("missing_controls", [])
    assumptions_file = sub_path / "assumptions.json"

    if not assumptions_file.exists():
        return (
            CheckOutcome.FAIL,
            f"assumptions.json 不存在，{len(missing_controls)} 个缺失控规条件未记录",
            str(assumptions_file),
        )

    try:
        assumptions = json.loads(assumptions_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return (CheckOutcome.FAIL, "assumptions.json 不是合法 JSON", str(assumptions_file))

    # Check if each missing control has a corresponding assumption entry
    entries = assumptions if isinstance(assumptions, list) else assumptions.get("entries", [])
    covered = set()
    for entry in entries:
        if isinstance(entry, dict):
            for ctrl in missing_controls:
                if ctrl.lower() in str(entry).lower():
                    covered.add(ctrl)

    uncovered = [c for c in missing_controls if c not in covered]
    if uncovered:
        return (
            CheckOutcome.FAIL,
            f"{len(uncovered)} 个缺失控规条件未在 assumptions.json 中记录: {', '.join(uncovered)}",
            f"assumptions.json: missing controls {uncovered}",
        )
    return (CheckOutcome.PASS, f"全部 {len(missing_controls)} 个缺失控规条件已记录", "")


def _check_source_authority(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check no provisional sources are upgraded to formal."""
    provisional_ids = set(params.get("provisional_source_ids", []))
    sources_file = sub_path / "sources.json"

    if not sources_file.exists():
        return (CheckOutcome.SKIP, "sources.json 不存在", "")

    try:
        sources = json.loads(sources_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return (CheckOutcome.FAIL, "sources.json 不是合法 JSON", str(sources_file))

    entries = sources if isinstance(sources, list) else sources.get("entries", [])
    violations = []
    for entry in entries:
        sid = entry.get("source_id", "")
        if sid in provisional_ids:
            usage = entry.get("used_for", "")
            formal_fields = params.get("formal_required_fields", [])
            for field in formal_fields:
                if field in str(entry).lower():
                    violations.append(f"{sid}: provisional source used for '{field}'")
                    break

    if violations:
        return (
            CheckOutcome.FAIL,
            f"{len(violations)} 处 provisional 来源被升级使用",
            "\n".join(violations[:5]),
        )
    return (CheckOutcome.PASS, "无 provisional 来源越级使用", "")


def _check_sanity_bounds(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check metric values are within sanity bounds."""
    metric_key = params.get("metric_key", "")
    min_val = params.get("min_val")
    max_val = params.get("max_val")

    metrics_file = sub_path / "metrics.json"
    if not metrics_file.exists():
        return (CheckOutcome.SKIP, "metrics.json 不存在", "")

    try:
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return (CheckOutcome.FAIL, "metrics.json 不是合法 JSON", str(metrics_file))

    # Find the metric value
    value = None
    if isinstance(metrics, dict):
        # Try top-level first
        value = metrics.get(metric_key)
        # Try nested metrics.{key}.value
        if value is None and isinstance(metrics.get("metrics"), dict):
            entry = metrics["metrics"].get(metric_key)
            if isinstance(entry, dict):
                value = entry.get("value")
    elif isinstance(metrics, list):
        for m in metrics:
            if isinstance(m, dict):
                val = m.get("value") if m.get("metric") == metric_key else None
                if val is not None:
                    value = val
                    break
                # also try direct key
                if metric_key in m:
                    value = m[metric_key]
                    break

    if value is None:
        return (CheckOutcome.SKIP, f"metrics.json 中未找到 {metric_key}", "")

    if min_val is not None and value < min_val:
        return (
            CheckOutcome.FAIL,
            f"{metric_key} = {value} < 合理下限 {min_val}",
            f"metrics.json: {metric_key}={value}, min={min_val}",
        )
    if max_val is not None and value > max_val:
        return (
            CheckOutcome.FAIL,
            f"{metric_key} = {value} > 合理上限 {max_val}",
            f"metrics.json: {metric_key}={value}, max={max_val}",
        )

    return (CheckOutcome.PASS, f"{metric_key} = {value} 在合理范围内 [{min_val}, {max_val}]", "")


def _check_enum_values(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check GeoJSON features use valid enum values."""
    enum_name = params.get("enum_name", "")
    valid_codes = set(params.get("valid_codes", []))
    target_field = params.get("target_geojson_field", "")

    if not valid_codes:
        return (CheckOutcome.SKIP, f"{enum_name} 无有效枚举值", "")

    # Find the relevant GeoJSON file
    geometry_dir = sub_path / "geometry"
    violations = []
    for geojson_file in geometry_dir.glob("*.geojson"):
        data = json.loads(geojson_file.read_text(encoding="utf-8"))
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            code = props.get(target_field, "")
            if code and code not in valid_codes:
                feat_id = props.get("id", "?")
                violations.append(f"{geojson_file.name}#{feat_id}: '{code}' not in {enum_name}")

    if violations:
        return (
            CheckOutcome.FAIL,
            f"{len(violations)} 个 feature 使用了无效的 {enum_name} 值",
            "\n".join(violations[:5]),
        )
    return (CheckOutcome.PASS, f"所有 {enum_name} 值合法", "")


def _check_crs_used(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Verify EPSG:4548 is actually used in metrics."""
    # This is a soft check — we verify the metrics.json mentions EPSG:4548
    metrics_file = sub_path / "metrics.json"
    if not metrics_file.exists():
        return (CheckOutcome.SKIP, "metrics.json 不存在", "")

    text = metrics_file.read_text(encoding="utf-8")
    if "4548" in text or "EPSG:4548" in text:
        return (CheckOutcome.PASS, "metrics 引用了 EPSG:4548", "")

    return (
        CheckOutcome.FAIL,
        "metrics.json 未引用 EPSG:4548 投影坐标系",
        f"metrics.json: no EPSG:4548 reference found",
    )


def _check_locked_layers(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Verify locked layers are not modified."""
    locked = set(params.get("locked_layers", []))
    geometry_dir = sub_path / "geometry"
    violations = []

    for geojson_file in geometry_dir.glob("*.geojson"):
        data = json.loads(geojson_file.read_text(encoding="utf-8"))
        for feat in data.get("features", []):
            layer = feat.get("properties", {}).get("layer", "")
            if layer in locked:
                feat_id = feat.get("properties", {}).get("id", "?")
                violations.append(f"{geojson_file.name}#{feat_id}: locked layer '{layer}'")

    if violations:
        return (
            CheckOutcome.FAIL,
            f"锁定图层中发现 {len(violations)} 个 feature（锁定图层不应出现在提交中）",
            "\n".join(violations[:5]),
        )
    return (CheckOutcome.PASS, "无锁定图层被修改", "")


def _check_layer_names(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check all feature layer names are valid."""
    valid = set(params.get("valid_layers", []))
    geometry_dir = sub_path / "geometry"
    violations = []

    for geojson_file in geometry_dir.glob("*.geojson"):
        data = json.loads(geojson_file.read_text(encoding="utf-8"))
        for feat in data.get("features", []):
            layer = feat.get("properties", {}).get("layer", "")
            if layer and layer not in valid:
                feat_id = feat.get("properties", {}).get("id", "?")
                violations.append(f"{geojson_file.name}#{feat_id}: unknown layer '{layer}'")

    if violations:
        return (
            CheckOutcome.FAIL,
            f"{len(violations)} 个 feature 使用了未知图层名",
            "\n".join(violations[:5]),
        )
    return (CheckOutcome.PASS, "所有图层名合法", "")
