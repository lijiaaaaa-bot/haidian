#!/usr/bin/env python3
"""Remote benchmark of open-city-ai/haidian submissions without full clone.

Fetches Git tree + self_check/metrics/manifest JSON and core figure sizes for top-N.
Writes data/benchmark/submissions_ranking.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import concurrent.futures
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DEFAULT = REPO / "data" / "benchmark" / "submissions_ranking.json"
BASE = "https://raw.githubusercontent.com/open-city-ai/haidian/main"
TREE_URL = "https://api.github.com/repos/open-city-ai/haidian/git/trees/main?recursive=1"

CORE_FIGS = [
    "site-overview.png", "land-use-structure.png", "key-areas.png",
    "mobility-bluegreen.png", "metrics-evidence.png",
]


def fetch(url: str, binary: bool = False, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "haidian-benchmark/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if binary else r.read().decode("utf-8", errors="replace")


def fetch_json(path: str):
    return json.loads(fetch(f"{BASE}/{path}"))


def metric_val(met: dict, key: str):
    if not met or "__error__" in met:
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


def figure_kb(login: str, slug: str) -> float | None:
    total = 0
    ok = 0
    for fn in CORE_FIGS:
        try:
            total += len(fetch(
                f"{BASE}/submissions/{login}/{slug}/assets/figures/{fn}", binary=True
            ))
            ok += 1
        except Exception:
            pass
    return round(total / 1024, 1) if ok >= 3 else None


def score(rec: dict) -> float:
    s = 0.0
    if rec.get("all_pass"):
        s += 100
    if rec.get("package_state") == "ready_for_review":
        s += 50
    lu = rec.get("land_use") or 0
    s += lu * 3 + (rec.get("buildings") or 0) + (rec.get("roads") or 0) * 0.5
    kb = rec.get("figure_kb") or 0
    s += min(kb / 10, 200)  # up to +200 for large figures
    return s


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=30, help="Deep-fetch figure KB for top N")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--refresh", action="store_true", help="Alias for default run")
    args = parser.parse_args()

    print("Fetching git tree...", flush=True)
    tree = json.loads(fetch(TREE_URL))
    packages: dict[tuple[str, str], dict] = defaultdict(lambda: {"figures": []})
    for item in tree.get("tree", []):
        p = item["path"]
        m = re.match(r"submissions/([^/]+)/([^/]+)/(.+)", p)
        if not m:
            continue
        login, slug, rest = m.groups()
        key = (login, slug)
        if rest in ("self_check.json", "metrics.json", "manifest.json"):
            packages[key][rest] = p
        elif rest.startswith("assets/figures/") and rest.endswith(".png"):
            packages[key]["figures"].append(rest)

    paths = []
    for info in packages.values():
        for k in ("self_check.json", "metrics.json", "manifest.json"):
            if k in info:
                paths.append(info[k])

    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as ex:
        futs = {ex.submit(fetch_json, p): p for p in paths}
        for fut in concurrent.futures.as_completed(futs):
            results[futs[fut]] = fut.result()

    records = []
    for (login, slug), info in packages.items():
        sc = results.get(info.get("self_check.json"), {})
        met = results.get(info.get("metrics.json"), {})
        man = results.get(info.get("manifest.json"), {})
        checks = sc.get("checks") or []
        all_pass = len(checks) > 0 and all(
            c.get("result") in ("pass", "PASS") for c in checks if isinstance(c, dict)
        )
        rec = {
            "login": login,
            "slug": slug,
            "title": (man or {}).get("proposal_title") or (man or {}).get("title"),
            "package_state": (sc or {}).get("package_state") or (man or {}).get("package_state"),
            "all_pass": all_pass,
            "figures": len(info.get("figures", [])),
            "land_use": metric_val(met, "land_use_feature_count"),
            "buildings": metric_val(met, "building_feature_count"),
            "roads": metric_val(met, "road_feature_count"),
        }
        for k in ("land_use", "buildings", "roads"):
            if rec[k] is not None:
                try:
                    rec[k] = int(float(rec[k]))
                except (TypeError, ValueError):
                    rec[k] = None
        records.append(rec)

    # Rank without figure KB first
    for r in records:
        r["_score"] = score(r)
    records.sort(key=lambda x: x["_score"], reverse=True)

    # Deep figure KB for top N
    top_n = records[: args.top]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {
            ex.submit(figure_kb, r["login"], r["slug"]): r
            for r in top_n
        }
        for fut in concurrent.futures.as_completed(futs):
            r = futs[fut]
            r["figure_kb"] = fut.result()
            r["_score"] = score(r)

    records.sort(key=lambda x: x["_score"], reverse=True)
    for r in records:
        r.pop("_score", None)

    stats = {
        "total_packages": len(records),
        "all_pass": sum(1 for r in records if r.get("all_pass")),
        "ready_for_review": sum(1 for r in records if r.get("package_state") == "ready_for_review"),
        "metrics_land_use_populated": sum(1 for r in records if r.get("land_use") is not None),
        "figure_count_modes": Counter(r.get("figures", 0) for r in records).most_common(5),
    }

    payload = {
        "generated_at": "remote-fetch",
        "source": "open-city-ai/haidian@main",
        "stats": stats,
        "top30": records[:30],
        "methodology": {
            "figure_kb": "sum of 5 core PNG HTTP GET sizes",
            "land_use": "metrics.json land_use_feature_count (often null)",
            "accuracy": "see docs/subprojects/top1-breakdown.md",
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} ({stats['total_packages']} packages, top figure_kb={records[0].get('figure_kb')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
