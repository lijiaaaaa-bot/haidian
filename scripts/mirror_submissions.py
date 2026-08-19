#!/usr/bin/env python3
"""Mirror open-city-ai/haidian submission packages for local re-evaluation.

Downloads all files under submissions/<login>/<slug>/ from upstream main.
Supports resume, manifest tracking, and analysis vs full tiers.

Usage:
  python3 scripts/mirror_submissions.py --tier full
  python3 scripts/mirror_submissions.py --tier analysis --workers 32
  python3 scripts/mirror_submissions.py --include-local submissions/lijiaaaaa-bot/jingzhang-zhimai-belt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MIRROR = REPO / "data" / "benchmark" / "mirror"
BASE = "https://raw.githubusercontent.com/open-city-ai/haidian/main"
TREE_URL = "https://api.github.com/repos/open-city-ai/haidian/git/trees/main?recursive=1"

# Skip large/binary patterns in analysis tier (still fetch json/geojson/png/md/html)
ANALYSIS_SKIP_SUFFIXES = {".pdf", ".zip", ".mp4", ".mov"}
ANALYSIS_SKIP_PARTS = {"/drawings/"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, binary: bool = True, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "haidian-mirror/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def load_tree(cache_path: Path, refresh: bool) -> dict:
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    print("Fetching git tree...", flush=True)
    raw = fetch(TREE_URL, binary=False, timeout=180)
    tree = json.loads(raw.decode("utf-8"))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
    return tree


def tier_include(rel_path: str, tier: str) -> bool:
    if tier == "full":
        return True
    lower = rel_path.lower()
    for part in ANALYSIS_SKIP_PARTS:
        if part in lower:
            return False
    for suf in ANALYSIS_SKIP_SUFFIXES:
        if lower.endswith(suf):
            return False
    return True


def group_packages(tree: dict, tier: str) -> dict[tuple[str, str], list[dict]]:
    packages: dict[tuple[str, str], list[dict]] = defaultdict(list)
    pat = re.compile(r"^submissions/([^/]+)/([^/]+)/(.+)$")
    for item in tree.get("tree", []):
        if item.get("type") != "blob":
            continue
        m = pat.match(item["path"])
        if not m:
            continue
        login, slug, rest = m.groups()
        if not tier_include(item["path"], tier):
            continue
        packages[(login, slug)].append(
            {"path": item["path"], "size": item.get("size", 0), "rest": rest}
        )
    return packages


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_one(rel_path: str, dest: Path, expected_size: int, retries: int = 5) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        local_size = dest.stat().st_size
        if expected_size and local_size == expected_size:
            return {"path": rel_path, "status": "skipped", "bytes": local_size}
        if expected_size == 0 and local_size > 0:
            return {"path": rel_path, "status": "skipped", "bytes": local_size}

    url = f"{BASE}/{rel_path}"
    last_err = ""
    for attempt in range(retries):
        try:
            data = fetch(url, binary=True)
            dest.write_bytes(data)
            return {
                "path": rel_path,
                "status": "ok",
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (403, 429) and attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            break
        except Exception as e:
            last_err = str(e)[:200]
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 8))
                continue
            break
    return {"path": rel_path, "status": "error", "error": last_err}


def copy_local_package(src: Path, mirror_root: Path, login: str, slug: str) -> None:
    dest = mirror_root / "packages" / login / slug
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    print(f"Copied local package → {dest.relative_to(REPO)}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror upstream submission packages locally")
    parser.add_argument("--mirror-root", type=Path, default=DEFAULT_MIRROR)
    parser.add_argument("--tier", choices=("analysis", "full"), default="full")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--refresh-tree", action="store_true")
    parser.add_argument("--include-local", type=Path, default=None,
                        help="Copy a local submission into mirror/packages/<login>/<slug>")
    parser.add_argument("--local-login", default="lijiaaaaa-bot")
    parser.add_argument("--local-slug", default="jingzhang-zhimai-belt")
    parser.add_argument("--max-packages", type=int, default=0, help="Limit packages (0=all)")
    args = parser.parse_args()

    mirror_root = args.mirror_root.resolve()
    packages_dir = mirror_root / "packages"
    manifest_path = mirror_root / "manifest.json"
    tree_cache = mirror_root / "tree_cache.json"

    tree = load_tree(tree_cache, args.refresh_tree)
    packages = group_packages(tree, args.tier)
    keys = sorted(packages.keys())
    if args.max_packages:
        keys = keys[: args.max_packages]

    total_files = sum(len(packages[k]) for k in keys)
    total_bytes = sum(f["size"] for k in keys for f in packages[k])
    print(
        f"Tier={args.tier}: {len(keys)} packages, {total_files} files, "
        f"~{total_bytes / (1024**3):.2f} GB",
        flush=True,
    )

    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest.update({
        "source": "open-city-ai/haidian@main",
        "tier": args.tier,
        "updated_at": utc_now(),
        "packages_total": len(keys),
        "files_total": total_files,
        "bytes_total": total_bytes,
        "packages": manifest.get("packages", {}),
        "file_index": manifest.get("file_index", {}),
    })
    if "started_at" not in manifest:
        manifest["started_at"] = utc_now()

    tasks: list[tuple[str, Path, int]] = []
    for login, slug in keys:
        pkg_key = f"{login}/{slug}"
        pkg_manifest = manifest["packages"].setdefault(pkg_key, {
            "login": login,
            "slug": slug,
            "files_total": len(packages[(login, slug)]),
            "files_done": 0,
            "bytes_done": 0,
            "status": "pending",
        })
        if pkg_manifest.get("status") == "complete":
            continue
        for finfo in packages[(login, slug)]:
            rel = finfo["path"]
            dest = packages_dir / login / slug / finfo["rest"]
            idx = manifest["file_index"].get(rel, {})
            if idx.get("status") == "ok" and dest.is_file():
                continue
            tasks.append((rel, dest, finfo.get("size") or 0))

    print(f"Download queue: {len(tasks)} files (resume skips completed)", flush=True)
    done = 0
    errors = 0
    t0 = time.time()

    def on_result(rel: str, result: dict) -> None:
        nonlocal done, errors
        manifest["file_index"][rel] = {
            **result,
            "at": utc_now(),
        }
        login, slug = rel.split("/")[1:3]
        pkg_key = f"{login}/{slug}"
        pkg = manifest["packages"][pkg_key]
        if result.get("status") in ("ok", "skipped"):
            pkg["files_done"] = sum(
                1 for p, v in manifest["file_index"].items()
                if p.startswith(f"submissions/{login}/{slug}/") and v.get("status") in ("ok", "skipped")
            )
            pkg["bytes_done"] = sum(
                v.get("bytes", 0) for p, v in manifest["file_index"].items()
                if p.startswith(f"submissions/{login}/{slug}/") and v.get("status") in ("ok", "skipped")
            )
            if pkg["files_done"] >= pkg["files_total"]:
                pkg["status"] = "complete"
            else:
                pkg["status"] = "partial"
        else:
            errors += 1
            pkg["status"] = "partial"
        done += 1
        if done % 200 == 0 or done == len(tasks):
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0
            print(f"  {done}/{len(tasks)} files ({rate:.1f}/s, errors={errors})", flush=True)
            manifest["updated_at"] = utc_now()
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(download_one, rel, dest, sz): rel for rel, dest, sz in tasks}
        for fut in as_completed(futs):
            rel = futs[fut]
            try:
                result = fut.result()
            except Exception as e:
                result = {"path": rel, "status": "error", "error": str(e)[:200]}
            on_result(rel, result)

    manifest["updated_at"] = utc_now()
    complete = sum(1 for p in manifest["packages"].values() if p.get("status") == "complete")
    manifest["packages_complete"] = complete
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest → {manifest_path.relative_to(REPO)} ({complete}/{len(keys)} packages complete)", flush=True)

    if args.include_local:
        src = args.include_local.resolve()
        if not src.is_dir():
            print(f"ERROR: --include-local not a directory: {src}", file=sys.stderr)
            return 1
        copy_local_package(src, mirror_root, args.local_login, args.local_slug)
        manifest["local_package"] = {
            "login": args.local_login,
            "slug": args.local_slug,
            "source": str(src.relative_to(REPO)) if REPO in src.parents else str(src),
            "copied_at": utc_now(),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
