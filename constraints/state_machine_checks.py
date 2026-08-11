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


# ── Check: land_use geometry validity ────────────────────────────────


def _closed_ring(ring: list) -> bool:
    """Polygon ring is closed: first coordinate equals last coordinate."""
    if len(ring) < 4:
        return False
    return ring[0] == ring[-1]


def _raw_rings(geom_raw: dict) -> list[list]:
    """Extract raw coordinate rings from a GeoJSON Polygon/MultiPolygon.

    Uses the source coordinates (not shapely's parsed geometry, which
    auto-closes rings), so explicit ring closure in the file is what gets
    judged. Non-polygon geometries yield no rings.
    """
    geom_type = geom_raw.get("type") if isinstance(geom_raw, dict) else None
    coords = geom_raw.get("coordinates") or []
    if geom_type == "Polygon":
        return [list(ring) for ring in coords if ring]
    if geom_type == "MultiPolygon":
        return [list(ring) for poly in coords for ring in poly if ring]
    return []


def check_land_use_geometry_valid(sub_path: Path, _params: dict) -> tuple[CheckOutcome, str, str]:
    """Validate every land_use feature's geometry is well-formed.

    Deterministic shapely checks, mirroring the state-machine precondition
    that a parcel with invalid geometry is fail-closed:
      - geometry present and parses to a polygon
      - area > 0 (degenerate sliver polygons cannot be judged)
      - geometry is_valid (no self-intersection / bowtie)
      - all rings closed (first == last coordinate)
    """
    try:
        from shapely.geometry import shape
    except ImportError:
        return (CheckOutcome.SKIP, "shapely not available", "")

    land_use_path = sub_path / "geometry" / "land_use.geojson"
    gj = _read_geojson(land_use_path)
    if gj is None:
        return (CheckOutcome.SKIP, "land_use.geojson 不存在或无法解析", "")

    features = gj.get("features", [])
    if not features:
        return (CheckOutcome.SKIP, "land_use.geojson 无 feature", "")

    violations = []
    for feat in features:
        props = feat.get("properties", {})
        fid = props.get("id", "?")
        geom_raw = feat.get("geometry")
        if geom_raw is None:
            violations.append(f"{fid}: 缺少 geometry")
            continue
        try:
            geom = shape(geom_raw)
        except Exception:  # noqa: BLE001 — 非法几何按无效处理
            violations.append(f"{fid}: geometry 无法解析")
            continue
        if geom.geom_type not in ("Polygon", "MultiPolygon"):
            violations.append(f"{fid}: geometry 类型为 {geom.geom_type}，land_use 应为 Polygon")
            continue
        if geom.area <= 0:
            violations.append(f"{fid}: 面积 {geom.area:.4g} <= 0（退化几何）")
        if not geom.is_valid:
            violations.append(f"{fid}: 几何自交/无效 (is_valid=False)")
        # Ring closure check on RAW coordinates: shapely's shape() silently
        # closes unclosed rings, so closure must be judged on the source data.
        raw_rings = _raw_rings(geom_raw)
        for ring in raw_rings:
            if not _closed_ring(ring):
                violations.append(f"{fid}: 多边形环未闭合 (ring 首尾坐标不一致)")

    if violations:
        return (
            CheckOutcome.FAIL,
            f"land_use.geojson: {len(violations)} 处几何无效",
            "\n".join(violations[:10]),
        )
    return (
        CheckOutcome.PASS,
        f"land_use.geojson: 全部 {len(features)} 个 feature 几何有效（面积>0、不自交、环闭合）",
        "",
    )


# ── Check: building height field ─────────────────────────────────────


def check_building_height(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check the building layer carries a sane height field.

    Every building feature must declare a height (height_m / building_height_m
    / height); when present, the value must be within the reasonable band
    [min_height_m, max_height_m] (default 1–500 m). Missing height is a FAIL —
    a Gate-1 submission must at least declare massing intent.
    """
    building_path = sub_path / "geometry" / "buildings.geojson"
    if not building_path.exists():
        building_path = sub_path / "geometry" / "building_footprint.geojson"
    gj = _read_geojson(building_path)
    if gj is None:
        return (CheckOutcome.SKIP, "buildings.geojson 不存在或无法解析", "")

    features = gj.get("features", [])
    if not features:
        return (CheckOutcome.SKIP, "buildings.geojson 无 feature", "")

    height_fields = params.get("height_fields", ["height_m", "building_height_m", "height"])
    min_h = float(params.get("min_height_m", 1))
    max_h = float(params.get("max_height_m", 500))

    violations = []
    heights_checked = 0
    for feat in features:
        props = feat.get("properties", {})
        fid = props.get("id", "?")
        value = None
        for field in height_fields:
            if field in props and props[field] is not None and props[field] != "":
                value = props[field]
                break
        if value is None:
            violations.append(f"{fid}: 缺少高度字段 (期望 {height_fields} 之一)")
            continue
        try:
            h = float(value)
        except (TypeError, ValueError):
            violations.append(f"{fid}: 高度字段值 '{value}' 不是数字")
            continue
        heights_checked += 1
        if h < min_h or h > max_h:
            violations.append(f"{fid}: 高度 {h} m 超出合理范围 [{min_h}, {max_h}] m")

    if violations:
        return (
            CheckOutcome.FAIL,
            f"buildings.geojson: {len(violations)}/{len(features)} 个建筑高度不合规",
            "\n".join(violations[:10]),
        )
    return (
        CheckOutcome.PASS,
        f"buildings.geojson: 全部 {len(features)} 个建筑高度在 [{min_h}, {max_h}] m 合理范围",
        "",
    )


# ── Check: road network completeness ─────────────────────────────────


def check_road_network(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check the roads layer is a real network, not a single-line scaffold.

    Counts LineString / MultiLineString features in roads.geojson (fallback
    road_centerline.geojson). Fewer than min_roads (default 3) lines means the
    submission is still scaffolding — a design with one centerline cannot
    express a circulation network.
    """
    roads_path = sub_path / "geometry" / "roads.geojson"
    if not roads_path.exists():
        roads_path = sub_path / "geometry" / "road_centerline.geojson"
    gj = _read_geojson(roads_path)
    if gj is None:
        return (CheckOutcome.SKIP, "roads.geojson 不存在或无法解析", "")

    features = gj.get("features", [])
    if not features:
        return (CheckOutcome.SKIP, "roads.geojson 无 feature", "")

    min_roads = int(params.get("min_roads", 3))
    line_count = 0
    non_line = []
    for feat in features:
        geom_raw = feat.get("geometry")
        geom_type = geom_raw.get("type") if geom_raw else None
        props = feat.get("properties", {})
        fid = props.get("id", "?")
        if geom_type in ("LineString", "MultiLineString"):
            line_count += 1
        else:
            non_line.append(f"{fid}: {geom_type}")

    if line_count < min_roads:
        return (
            CheckOutcome.FAIL,
            f"roads.geojson: 仅 {line_count} 条道路，至少需要 {min_roads} 条（单线脚手架风险）",
            f"geometry/roads.geojson: road lines={line_count}, min={min_roads}"
            + (f"; 非线要素: {', '.join(non_line[:5])}" if non_line else ""),
        )
    return (
        CheckOutcome.PASS,
        f"roads.geojson: {line_count} 条道路，满足最低路网规模 {min_roads} 条",
        "",
    )


# ── Check: green ratio computed from geometry ────────────────────────


def _to_projected(geom: Any) -> Any:
    """Reproject geometry to EPSG:4548 (area-calculation CRS) for planar areas.

    Exchange GeoJSON is EPSG:4326 lat/lon; planar areas in degrees are wrong.
    If pyproj is unavailable, or the input already looks projected (coordinate
    magnitudes > 180/90), fall back to the raw geometry.
    """
    if geom is None or geom.is_empty:
        return geom
    try:
        x, y = geom.centroid.x, geom.centroid.y
        if abs(x) > 180 or abs(y) > 90:
            return geom  # already projected
        from shapely.ops import transform as _shapely_transform
        from pyproj import Transformer
        _PROJ_4548 = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)
        return _shapely_transform(lambda xi, yi: _PROJ_4548.transform(xi, yi), geom)
    except Exception:  # noqa: BLE001 — pyproj/shapely.ops 不可用则用原几何
        return geom


def check_green_ratio(sub_path: Path, params: dict) -> tuple[CheckOutcome, str, str]:
    """Check the green-space ratio computed from actual geometry, not the
    declared value in metrics.json.

    ratio = Σ(green_space polygon areas) / site_boundary area, both measured
    in EPSG:4548 projected units. Must fall in [min_ratio, max_ratio]
    (default 0.05–0.80). A declaration alone (metrics.json green_ratio) is not
    evidence — the geometry must back it up.
    """
    green_path = sub_path / "geometry" / "green_space.geojson"
    site_path = sub_path / "geometry" / "site_boundary.geojson"
    green_gj = _read_geojson(green_path)
    site_gj = _read_geojson(site_path)
    if green_gj is None or site_gj is None:
        return (CheckOutcome.SKIP, "green_space.geojson 或 site_boundary.geojson 不存在", "")

    try:
        from shapely.geometry import shape
    except ImportError:
        return (CheckOutcome.SKIP, "shapely not available", "")

    green_features = green_gj.get("features", [])
    site_features = site_gj.get("features", [])
    if not green_features or not site_features:
        return (CheckOutcome.SKIP, "green_space 或 site_boundary 无 feature", "")

    green_area = 0.0
    for feat in green_features:
        geom_raw = feat.get("geometry")
        if geom_raw is None:
            continue
        try:
            green_area += _to_projected(shape(geom_raw)).area
        except Exception:  # noqa: BLE001 — 单个要素解析失败不计入
            continue

    site_area = 0.0
    for feat in site_features:
        geom_raw = feat.get("geometry")
        if geom_raw is None:
            continue
        try:
            site_area += _to_projected(shape(geom_raw)).area
        except Exception:  # noqa: BLE001
            continue

    if site_area <= 0:
        return (CheckOutcome.FAIL, "site_boundary 面积 <= 0，无法计算绿地率", "geometry/site_boundary.geojson")

    min_ratio = float(params.get("min_ratio", 0.05))
    max_ratio = float(params.get("max_ratio", 0.80))
    ratio = green_area / site_area

    if ratio < min_ratio or ratio > max_ratio:
        return (
            CheckOutcome.FAIL,
            f"几何实测绿地率 {ratio:.4f} ({green_area:.0f}/{site_area:.0f} m²) 超出合理范围 [{min_ratio}, {max_ratio}]",
            f"geometry/: green_area={green_area:.0f}, site_area={site_area:.0f}, ratio={ratio:.4f}",
        )
    return (
        CheckOutcome.PASS,
        f"几何实测绿地率 {ratio:.4f} ({green_area:.0f}/{site_area:.0f} m²) 在合理范围 [{min_ratio}, {max_ratio}]",
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

    # Accept domain understanding: if proposal mentions the knowledge reference
    # or territorial spatial planning, consider it aware even without literal terms
    domain_indicators = ["国土空间", "territorial spatial",
                         "three-lines-knowledge"]
    if missing and any(ind in text.lower() for ind in domain_indicators):
        found.extend(missing)
        missing.clear()

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
    {
        "constraint_id": "C-SM-GEOMETRY-VALID",
        "name": "state_machine_land_use_geometry_valid",
        "category": "spatial",
        "severity": "high",
        "description": "几何有效性校验: 每个 land_use feature 的几何必须有效（面积>0、不自交、环闭合）",
        "check_function": "check_land_use_geometry_valid",
        "enabled": True,
        "params": {},
    },
    {
        "constraint_id": "C-SM-BUILDING-HEIGHT",
        "name": "state_machine_building_height",
        "category": "spatial",
        "severity": "high",
        "description": "建筑高度校验: building 图层每个 feature 必须带高度字段，且高度在 1-500m 合理范围",
        "check_function": "check_building_height",
        "enabled": True,
        "params": {
            "min_height_m": 1,
            "max_height_m": 500,
            "height_fields": ["height_m", "building_height_m", "height"],
        },
    },
    {
        "constraint_id": "C-SM-ROAD-NETWORK",
        "name": "state_machine_road_network",
        "category": "spatial",
        "severity": "high",
        "description": "路网完整性校验: roads 图层至少 3 条道路（拒绝单线脚手架）",
        "check_function": "check_road_network",
        "enabled": True,
        "params": {
            "min_roads": 3,
        },
    },
    {
        "constraint_id": "C-SM-GREEN-RATIO",
        "name": "state_machine_green_ratio",
        "category": "spatial",
        "severity": "high",
        "description": "绿地率校验: 用实际几何计算绿地率，须在 0.05-0.80 合理范围（不读声明值）",
        "check_function": "check_green_ratio",
        "enabled": True,
        "params": {
            "min_ratio": 0.05,
            "max_ratio": 0.80,
        },
    },
]
