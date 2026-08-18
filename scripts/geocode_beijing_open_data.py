#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北京开放平台海淀子集地理编码（高德 Web 服务 /v3/geocode/geo）。

对 3 个海淀子集（幼儿园名录 284 / 社区卫生服务中心 222 / 社会公用充电站 196）
逐条地址地理编码：GCJ-02 → WGS84 转换，派生 CSV 新增
  source_row（原子集 1 基行号）/ geocode_query（实际请求地址）/
  lon_wgs84 / lat_wgs84 / geocode_status（ok|no_result|error|quota_exceeded）

纪律（沿用 fetch_gaode.py）：
  - 限速 ≥1s/请求；失败重试 3 次退避；配额类错误停止并标记剩余行
  - 断点续跑：已编码行（ok/no_result/error）跳过，不重复消耗配额
  - 不伪造坐标：失败/无结果一律留空 lon/lat + 状态标注

用法：
  python3 scripts/geocode_beijing_open_data.py [--datasets kindergarten,health,charging]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_gaode import gcj02_to_wgs84, load_keys  # noqa: E402

BASE = "https://restapi.amap.com/v3/geocode/geo"
USER_AGENT = "haidian-jingzhang-ai-belt-research/1.0 (城市设计研究用途)"
RATE_LIMIT_S = 1.0
QUOTA_ERRORS = ("DAILY_QUERY_OVER_LIMIT", "BUSY", "QUOTA_EXCEEDED",
                "DAILY_QUERY_OVER_LIMIT_FOR_KEY", "NO_PERMISSION")

DATASETS = {
    "kindergarten": {
        "name": "幼儿园名录",
        "src": "data/sources/beijing-data-open/幼儿园名录_海淀区.csv",
        "out": "data/sources/beijing-data-open/幼儿园名录_海淀区_geocoded.csv",
        "addr_col": "幼儿园地址",
    },
    "health": {
        "name": "社区卫生服务中心",
        "src": "data/sources/beijing-data-open/社区卫生服务中心_海淀区.csv",
        "out": "data/sources/beijing-data-open/社区卫生服务中心_海淀区_geocoded.csv",
        "addr_col": "地址",
    },
    "charging": {
        "name": "社会公用充电站",
        "src": "data/sources/beijing-data-open/社会公用充电站_海淀区.csv",
        "out": "data/sources/beijing-data-open/社会公用充电站_海淀区_geocoded.csv",
        "addr_col": "区县具体地址",
    },
}


def clean_address(addr: str) -> str:
    """地址清洗：去除空白/重复空白，缺少'北京市'前缀时补齐。"""
    a = " ".join(addr.strip().split())
    if "北京市" not in a:
        a = "北京市" + a
    return a


def geocode_one(keys: dict, address: str, retries: int = 3) -> dict:
    """单条地址编码，返回 {status, lon, lat}；GCJ-02→WGS84 在成功时转换。"""
    import urllib.parse

    qs = urllib.parse.urlencode({"address": address, "city": "北京", "key": keys["key"]})
    url = "%s?%s" % (BASE, qs)
    for attempt in range(retries):
        out = subprocess.run(["curl", "-s", "--max-time", "30", "-A", USER_AGENT, url],
                             capture_output=True)
        try:
            d = json.loads(out.stdout)
        except ValueError:
            time.sleep(2 * (attempt + 1))
            continue
        if d.get("status") != "1":
            info = d.get("info", "")
            if any(k in info for k in QUOTA_ERRORS):
                return {"status": "quota_exceeded", "lon": "", "lat": ""}
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return {"status": "error", "lon": "", "lat": ""}
        geos = d.get("geocodes") or []
        if not geos or not geos[0].get("location"):
            return {"status": "no_result", "lon": "", "lat": ""}
        lon_gcj, lat_gcj = [float(x) for x in geos[0]["location"].split(",")]
        lon, lat = gcj02_to_wgs84(lon_gcj, lat_gcj)
        return {"status": "ok", "lon": round(lon, 6), "lat": round(lat, 6)}
    return {"status": "error", "lon": "", "lat": ""}


def run_dataset(keys: dict, ds: dict) -> dict:
    src = ROOT / ds["src"]
    out = ROOT / ds["out"]
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    cols = list(rows[0].keys())
    new_cols = cols + ["source_row", "geocode_query", "lon_wgs84", "lat_wgs84", "geocode_status"]

    # 断点续跑：读已有输出，按 source_row 记忆
    done: dict[int, dict] = {}
    if out.exists():
        for r in csv.DictReader(open(out, encoding="utf-8-sig")):
            try:
                done[int(r["source_row"])] = r
            except (KeyError, ValueError):
                continue

    result_rows: list[dict] = []
    status_counts = {"ok": 0, "no_result": 0, "error": 0, "quota_exceeded": 0, "skipped_resume": 0}
    quota_hit = False
    last_flush = time.time()

    for i, row in enumerate(rows, start=1):
        rec = dict(row)
        rec["source_row"] = i
        if i in done:
            r = done[i]
            rec.update({k: r.get(k, "") for k in new_cols[len(cols):]})
            status_counts["skipped_resume"] += 1
            result_rows.append(rec)
            continue
        if quota_hit:
            rec.update({"geocode_query": "", "lon_wgs84": "", "lat_wgs84": "",
                        "geocode_status": "quota_exceeded"})
            status_counts["quota_exceeded"] += 1
            result_rows.append(rec)
            continue

        addr = clean_address(row.get(ds["addr_col"], ""))
        geo = geocode_one(keys, addr)
        status_counts[geo["status"]] += 1
        rec.update({"geocode_query": addr, "lon_wgs84": geo["lon"], "lat_wgs84": geo["lat"],
                    "geocode_status": geo["status"]})
        result_rows.append(rec)
        if geo["status"] == "quota_exceeded":
            quota_hit = True

        # 增量落盘（每 10 行或每次配额中断），防中断丢失进度
        if (i % 10 == 0) or quota_hit or time.time() - last_flush > 30:
            _write_csv(out, new_cols, result_rows)
            last_flush = time.time()
        time.sleep(RATE_LIMIT_S)

    _write_csv(out, new_cols, result_rows)
    return {"name": ds["name"], "total": len(rows), "counts": status_counts, "out": str(out)}


def _write_csv(path: Path, cols: list, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def main():
    ap = argparse.ArgumentParser(description="北京开放平台海淀子集地理编码")
    ap.add_argument("--datasets", default="kindergarten,health,charging",
                    help="逗号分隔：kindergarten,health,charging")
    args = ap.parse_args()
    keys = load_keys()
    for key in args.datasets.split(","):
        key = key.strip()
        if key not in DATASETS:
            continue
        res = run_dataset(keys, DATASETS[key])
        c = res["counts"]
        ok_rate = 100.0 * c["ok"] / res["total"] if res["total"] else 0
        print("%s：总 %d ｜ ok %d（%.1f%%）｜ no_result %d ｜ error %d ｜ quota %d ｜ 续跑跳过 %d → %s"
              % (res["name"], res["total"], c["ok"], ok_rate, c["no_result"],
                 c["error"], c["quota_exceeded"], c["skipped_resume"], res["out"]), flush=True)


if __name__ == "__main__":
    main()
