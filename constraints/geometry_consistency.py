"""Checks that metrics.json declarations agree with the submitted geometry.

The existing area checks compare metrics.json against constants in the brief,
and the sanity checks only assert a value falls inside a plausible range. Both
pass for a number that was never derived from the package's own GeoJSON, so a
declared green_ratio could sit at 2.1x the value the geometry supports while
every CODE check reported PASS.

These checks close that hole: for each declared metric with a mechanical
definition, recompute it from geometry/ in the project's area-calculation CRS
and require the two to agree. Declaration alone is not evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from constraints.engine import (
    MAINTAINER_GEOMETRY_FILENAMES,
    CheckOutcome,
    _find_metric_value,
    _to_projected,
)


def _layer_path(sub_path: Path, layer: str) -> Path:
    filename = MAINTAINER_GEOMETRY_FILENAMES.get(layer, f"{layer.lower()}.geojson")
    return sub_path / "geometry" / filename


def _layer_geometries(sub_path: Path, layer: str) -> list[Any] | None:
    """Projected geometries of a layer, or None when the layer is absent."""
    path = _layer_path(sub_path, layer)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    from shapely.geometry import shape

    geoms = []
    for feat in data.get("features", []):
        raw = feat.get("geometry")
        if raw is None:
            continue
        try:
            geoms.append(_to_projected(shape(raw)))
        except Exception:  # noqa: BLE001 — 单个要素解析失败不参与复算
            continue
    return geoms


def _union_area(geoms: list[Any]) -> float:
    """Dissolved area — overlapping features must not be double-counted."""
    if not geoms:
        return 0.0
    from shapely.ops import unary_union

    return unary_union(geoms).area


def _recompute(sub_path: Path, params: dict) -> tuple[float | None, str]:
    """Recompute a metric from geometry. Returns (value, description)."""
    source = params.get("source", "")
    layer = params.get("layer", "")

    if source == "feature_count":
        geoms = _layer_geometries(sub_path, layer)
        if geoms is None:
            return (None, f"{layer} 图层不存在")
        return (float(len(geoms)), f"{layer} 要素数")

    if source == "layer_area":
        geoms = _layer_geometries(sub_path, layer)
        if geoms is None:
            return (None, f"{layer} 图层不存在")
        return (_union_area(geoms), f"{layer} 并集面积")

    if source == "layer_ratio":
        geoms = _layer_geometries(sub_path, layer)
        site = _layer_geometries(sub_path, "SITE_BOUNDARY")
        if geoms is None:
            return (None, f"{layer} 图层不存在")
        if not site:
            return (None, "site_boundary 图层不存在或无要素")
        site_area = _union_area(site)
        if site_area <= 0:
            return (None, "site_boundary 面积为 0")
        return (_union_area(geoms) / site_area, f"{layer} 并集面积 / site_boundary 面积")

    return (None, f"未知的复算方式 '{source}'")


def check_metric_matches_geometry(
    sub_path: Path, params: dict
) -> tuple[CheckOutcome, str, str]:
    """Require a declared metric to match its recomputation from geometry."""
    metric_key = params.get("metric_key", "")
    tolerance_pct = params.get("tolerance_pct", 5.0)

    metrics_file = sub_path / "metrics.json"
    if not metrics_file.exists():
        return (CheckOutcome.SKIP, "metrics.json 不存在", "")
    try:
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return (CheckOutcome.FAIL, "metrics.json 不是合法 JSON", str(metrics_file))

    declared = _find_metric_value(metrics, metric_key)
    if declared is None:
        # A metric that is absent or explicitly pending has nothing to
        # contradict; C-AREA owns the "required key is missing" verdict.
        return (CheckOutcome.SKIP, f"metrics.json 未声明 {metric_key}", "")

    try:
        from shapely.geometry import shape  # noqa: F401 — 提前暴露缺依赖
    except ImportError:
        return (CheckOutcome.SKIP, "shapely not available", "")

    actual, how = _recompute(sub_path, params)
    if actual is None:
        return (CheckOutcome.SKIP, f"无法从几何复算 {metric_key}: {how}", "")

    if actual == 0:
        within = declared == 0
        deviation_pct = 0.0 if within else 100.0
    else:
        deviation_pct = abs(declared - actual) / abs(actual) * 100
        within = deviation_pct <= tolerance_pct

    if within:
        return (
            CheckOutcome.PASS,
            f"{metric_key} 声明值 {declared:,.6g} 与几何复算 {actual:,.6g} 一致"
            f"（偏差 {deviation_pct:.2f}%）",
            "",
        )
    return (
        CheckOutcome.FAIL,
        f"{metric_key} 声明值 {declared:,.6g} 与几何复算值 {actual:,.6g} 不符"
        f"（偏差 {deviation_pct:.1f}%，容差 {tolerance_pct}%）。复算方式：{how}。"
        f"请修正 metrics.json 或修正对应几何图层，二者必须一致",
        f"metrics.json: {metric_key}={declared} vs geometry recompute={actual}",
    )


# Code-defined registry entries (not derived from repo data files), merged by
# extractors.generate_registry the same way the C-SM entries are.
GEOMETRY_CONSISTENCY_REGISTRY_ENTRIES = [
    {
        "constraint_id": "C-CONSIST-SITE-AREA",
        "name": "declared_site_area_matches_geometry",
        "category": "metric",
        "severity": "critical",
        "description": "site_area_sqm 声明值必须与 site_boundary 几何复算一致",
        "check_function": "verify_metric_matches_geometry",
        "check_type": "CODE",
        "enabled": True,
        "params": {
            "metric_key": "site_area_sqm",
            "source": "layer_area",
            "layer": "SITE_BOUNDARY",
            "tolerance_pct": 1.0,
        },
    },
    {
        "constraint_id": "C-CONSIST-GREEN-RATIO",
        "name": "declared_green_ratio_matches_geometry",
        "category": "metric",
        "severity": "critical",
        "description": "green_ratio 声明值必须与 green_space/site_boundary 几何复算一致",
        "check_function": "verify_metric_matches_geometry",
        "check_type": "CODE",
        "enabled": True,
        "params": {
            "metric_key": "green_ratio",
            "source": "layer_ratio",
            "layer": "GREEN_SPACE",
            "tolerance_pct": 5.0,
        },
    },
    {
        "constraint_id": "C-CONSIST-PUBLIC-RATIO",
        "name": "declared_public_space_ratio_matches_geometry",
        "category": "metric",
        "severity": "critical",
        "description": "public_space_ratio 声明值必须与 public_space/site_boundary 几何复算一致",
        "check_function": "verify_metric_matches_geometry",
        "check_type": "CODE",
        "enabled": True,
        "params": {
            "metric_key": "public_space_ratio",
            "source": "layer_ratio",
            "layer": "PUBLIC_SPACE",
            "tolerance_pct": 5.0,
        },
    },
    {
        "constraint_id": "C-CONSIST-GREEN-AREA",
        "name": "declared_green_area_matches_geometry",
        "category": "metric",
        "severity": "high",
        "description": "green_space_area_sqm 声明值必须与 green_space 几何复算一致",
        "check_function": "verify_metric_matches_geometry",
        "check_type": "CODE",
        "enabled": True,
        "params": {
            "metric_key": "green_space_area_sqm",
            "source": "layer_area",
            "layer": "GREEN_SPACE",
            "tolerance_pct": 5.0,
        },
    },
    {
        "constraint_id": "C-CONSIST-PUBLIC-AREA",
        "name": "declared_public_space_area_matches_geometry",
        "category": "metric",
        "severity": "high",
        "description": "public_space_area_sqm 声明值必须与 public_space 几何复算一致",
        "check_function": "verify_metric_matches_geometry",
        "check_type": "CODE",
        "enabled": True,
        "params": {
            "metric_key": "public_space_area_sqm",
            "source": "layer_area",
            "layer": "PUBLIC_SPACE",
            "tolerance_pct": 5.0,
        },
    },
    {
        "constraint_id": "C-CONSIST-BUILDING-AREA",
        "name": "declared_building_footprint_area_matches_geometry",
        "category": "metric",
        "severity": "high",
        "description": "building_footprint_area_sqm 声明值必须与 buildings 几何复算一致",
        "check_function": "verify_metric_matches_geometry",
        "check_type": "CODE",
        "enabled": True,
        "params": {
            "metric_key": "building_footprint_area_sqm",
            "source": "layer_area",
            "layer": "BUILDING_FOOTPRINT",
            "tolerance_pct": 5.0,
        },
    },
    {
        "constraint_id": "C-CONSIST-KEY-AREA-COUNT",
        "name": "declared_key_area_count_matches_geometry",
        "category": "metric",
        "severity": "high",
        "description": "key_area_count 声明值必须与 key_areas 要素数一致",
        "check_function": "verify_metric_matches_geometry",
        "check_type": "CODE",
        "enabled": True,
        "params": {
            "metric_key": "key_area_count",
            "source": "feature_count",
            "layer": "KEY_AREA",
            "tolerance_pct": 0.0,
        },
    },
]
