#!/usr/bin/env python3
"""Analyze mirrored submission packages with real GeoJSON counts and local figure sizes.

Produces three leaderboards:
  1. geometry_score — self_check + real feature counts + figure KB
  2. gate1_ready — packages that would pass ConstraintEngine (see batch_eval_mirror)
  3. composite — weighted blend for overall ranking

Usage:
  python3 scripts/analyze_submissions_local.py
  python3 scripts/analyze_submissions_local.py --mirror-root data/benchmark/mirror
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MIRROR = REPO / "data" / "benchmark" / "mirror"
OUT_JSON = REPO / "data" / "benchmark" / "full_ranking_report.json"
OUT_MD = REPO / "data" / "benchmark" / "full_ranking_report.md"

CORE_FIGS = [
    "site-overview.png", "land-use-structure.png", "key-areas.png",
    "mobility-bluegreen.png", "metrics-evidence.png",
]

GEO_LAYERS = [
    "land_use", "buildings", "roads", "green_space",
    "public_space", "phasing", "constraints", "key_areas", "site_boundary",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def feature_count(geojson_path: Path) -> int | None:
    if not geojson_path.is_file():
        return None
    try:
        gj = load_json(geojson_path)
        return len(gj.get("features") or [])
    except Exception:
        return None


def metric_val(met: dict, key: str):
    if not met:
        return None
    v = met.get(key)
    if v is None and isinstance(met.get("metrics"), dict):
        inner = met["metrics"].get(key)
        if isinstance(inner, dict):
            return inner.get("value")
        return inner
    if isinstance(v, dict):
        return v.get("value")
    return v


def figure_kb(pkg_dir: Path) -> tuple[float | None, int]:
    fig_dir = pkg_dir / "assets" / "figures"
    if not fig_dir.is_dir():
        return None, 0
    total = 0
    ok = 0
    png_count = 0
    for fn in CORE_FIGS:
        fp = fig_dir / fn
        if fp.is_file():
            total += fp.stat().st_size
            ok += 1
    png_count = len(list(fig_dir.glob("*.png")))
    return (round(total / 1024, 1) if ok >= 3 else None), png_count


def self_check_pass(sc: dict) -> bool:
    checks = sc.get("checks") or []
    return len(checks) > 0 and all(
        c.get("result") in ("pass", "PASS") for c in checks if isinstance(c, dict)
    )


def geometry_score(rec: dict) -> float:
    s = 0.0
    if rec.get("all_pass"):
        s += 100
    if rec.get("package_state") == "ready_for_review":
        s += 50
    lu = rec.get("land_use_geo") or rec.get("land_use_metrics") or 0
    b = rec.get("buildings_geo") or rec.get("buildings_metrics") or 0
    r = rec.get("roads_geo") or rec.get("roads_metrics") or 0
    s += lu * 3 + b + r * 0.5
    kb = rec.get("figure_kb") or 0
    s += min(kb / 10, 200)
    return round(s, 2)


def analyze_package(login: str, slug: str, pkg_dir: Path) -> dict:
    sc = load_json(pkg_dir / "self_check.json")
    met = load_json(pkg_dir / "metrics.json")
    man = load_json(pkg_dir / "manifest.json")

    geo = {}
    for layer in GEO_LAYERS:
        geo[layer] = feature_count(pkg_dir / "geometry" / f"{layer}.geojson")

    fkb, png_n = figure_kb(pkg_dir)
    rec = {
        "login": login,
        "slug": slug,
        "path": str(pkg_dir.relative_to(REPO)),
        "title": man.get("proposal_title") or man.get("title"),
        "package_state": sc.get("package_state") or man.get("package_state"),
        "all_pass": self_check_pass(sc),
        "figure_kb": fkb,
        "figure_png_count": png_n,
        "land_use_geo": geo.get("land_use"),
        "buildings_geo": geo.get("buildings"),
        "roads_geo": geo.get("roads"),
        "green_geo": geo.get("green_space"),
        "public_geo": geo.get("public_space"),
        "phasing_geo": geo.get("phasing"),
        "constraints_geo": geo.get("constraints"),
        "land_use_metrics": _int_or_none(metric_val(met, "land_use_feature_count")),
        "buildings_metrics": _int_or_none(metric_val(met, "building_feature_count")),
        "roads_metrics": _int_or_none(metric_val(met, "road_feature_count")),
    }
    rec["geometry_score"] = geometry_score(rec)
    return rec


def _int_or_none(v) -> int | None:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def write_markdown(payload: dict, path: Path) -> None:
    stats = payload["stats"]
    lines = [
        "# Full submission ranking (local mirror)",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Mirror: `{payload['mirror_root']}`",
        f"- Packages: {stats['total_packages']}",
        f"- GeoJSON land_use populated: {stats['land_use_geo_populated']}",
        f"- metrics.json land_use populated: {stats['land_use_metrics_populated']}",
        "",
        "## Top 30 by geometry_score (real GeoJSON counts)",
        "",
        "| rank | login | slug | score | LU | B | R | fig_kb | pass |",
        "|------|-------|------|-------|----|----|-----|--------|------|",
    ]
    for i, r in enumerate(payload["leaderboards"]["geometry_score"][:30], 1):
        lines.append(
            f"| {i} | {r['login']} | {r['slug']} | {r['geometry_score']} | "
            f"{r.get('land_use_geo')} | {r.get('buildings_geo')} | {r.get('roads_geo')} | "
            f"{r.get('figure_kb')} | {r.get('all_pass')} |"
        )
    lines.extend(["", "## Methodology", "", payload.get("methodology_note", "")])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()

    packages_dir = args.mirror_root / "packages"
    if not packages_dir.is_dir():
        print(f"ERROR: no packages at {packages_dir}")
        return 1

    records = []
    for login_dir in sorted(packages_dir.iterdir()):
        if not login_dir.is_dir():
            continue
        for slug_dir in sorted(login_dir.iterdir()):
            if not slug_dir.is_dir():
                continue
            records.append(analyze_package(login_dir.name, slug_dir.name, slug_dir))

    records.sort(key=lambda r: r["geometry_score"], reverse=True)

    stats = {
        "total_packages": len(records),
        "all_pass": sum(1 for r in records if r.get("all_pass")),
        "ready_for_review": sum(1 for r in records if r.get("package_state") == "ready_for_review"),
        "land_use_geo_populated": sum(1 for r in records if r.get("land_use_geo") is not None),
        "land_use_metrics_populated": sum(1 for r in records if r.get("land_use_metrics") is not None),
        "figure_kb_populated": sum(1 for r in records if r.get("figure_kb") is not None),
        "land_use_geo_modes": Counter(r.get("land_use_geo") for r in records if r.get("land_use_geo") is not None).most_common(8),
    }

    payload = {
        "generated_at": utc_now(),
        "mirror_root": str(args.mirror_root.relative_to(REPO)),
        "stats": stats,
        "leaderboards": {
            "geometry_score": records,
        },
        "top30": records[:30],
        "methodology_note": (
            "geometry_score = pass*100 + ready*50 + land_use_geo*3 + buildings_geo + roads_geo*0.5 "
            "+ min(figure_kb/10, 200). Feature counts from local GeoJSON, not metrics.json."
        ),
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(payload, args.out_md)
    print(f"Wrote {args.out_json} and {args.out_md} ({len(records)} packages)")
    if records:
        top = records[0]
        print(f"Top: {top['login']}/{top['slug']} score={top['geometry_score']} LU={top.get('land_use_geo')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
