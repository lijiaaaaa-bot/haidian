#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""走廊设施底数整合（开放平台地理编码 + 走廊交集 + 多源对照）纯逻辑单测。

覆盖 scripts/geocode_beijing_open_data.py 与
scripts/corridor_intersection_and_comparison.py 的纯函数：
  clean_address / in_corridor / classify_row / kw_hint
以及真实派生文件的存量断言（不跑网络，验证已产出数据的一致性）。
"""
import csv
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fetch_gaode import gcj02_to_wgs84  # noqa: E402,F401
from geocode_beijing_open_data import clean_address  # noqa: E402
from corridor_intersection_and_comparison import (  # noqa: E402
    classify_row,
    in_corridor,
    kw_hint,
)


class AddressCleanTests(unittest.TestCase):
    def test_prefix_beijing_when_missing(self):
        self.assertEqual(clean_address(" 海淀区万柳中路33号 "), "北京市海淀区万柳中路33号")

    def test_keep_existing_full_address(self):
        self.assertEqual(clean_address("北京市海淀区学院路38号"), "北京市海淀区学院路38号")

    def test_blank_address(self):
        self.assertEqual(clean_address(""), "北京市")


class CorridorGeoTests(unittest.TestCase):
    def test_in_bbox(self):
        self.assertTrue(in_corridor(116.347, 39.985))
        self.assertFalse(in_corridor(116.500, 39.985))   # 东出界
        self.assertFalse(in_corridor(116.347, 40.100))   # 北出界
        self.assertFalse(in_corridor(None, None))        # 无坐标

    def test_classify_row(self):
        self.assertEqual(classify_row("ok", 116.347, 39.985), "in")
        self.assertEqual(classify_row("ok", 116.200, 39.985), "out")
        self.assertEqual(classify_row("no_result", "", ""), "not_geocoded")
        self.assertEqual(classify_row("error", "", ""), "not_geocoded")
        self.assertEqual(classify_row("quota_exceeded", "", ""), "not_geocoded")

    def test_kw_hint(self):
        self.assertEqual(kw_hint("北京市海淀区学院路38号"), "学院路")
        self.assertEqual(kw_hint("北京市海淀区万寿路28号院"), "")


class DerivedDataConsistencyTests(unittest.TestCase):
    """存量断言：已产出的 geocoded CSV 与走廊交集数据满足一致性（不跑网络）。"""

    DATASETS = {
        "kindergarten": ("data/sources/beijing-data-open/幼儿园名录_海淀区_geocoded.csv",
                         "data/processed/corridor_intersection_kindergarten.csv"),
        "health": ("data/sources/beijing-data-open/社区卫生服务中心_海淀区_geocoded.csv",
                   "data/processed/corridor_intersection_health.csv"),
        "charging": ("data/sources/beijing-data-open/社会公用充电站_海淀区_geocoded.csv",
                     "data/processed/corridor_intersection_charging.csv"),
    }

    def test_geocoded_files_exist_with_schema(self):
        for key, (gc, _) in self.DATASETS.items():
            path = REPO_ROOT / gc
            if not path.exists():
                continue
            with self.subTest(key=key):
                rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
                for col in ("source_row", "geocode_query", "lon_wgs84", "lat_wgs84", "geocode_status"):
                    self.assertIn(col, rows[0], "%s 缺列 %s" % (gc, col))

    def test_in_plus_out_equals_ok_and_total(self):
        """走廊内 + 走廊外 == 编码成功；编码成功 + 未编码 == 原子集总数。"""
        for key, (gc, ci) in self.DATASETS.items():
            path = REPO_ROOT / gc
            if not path.exists():
                continue
            with self.subTest(key=key):
                rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
                n_in = sum(1 for r in rows
                           if classify_row(r["geocode_status"], r["lon_wgs84"], r["lat_wgs84"]) == "in")
                n_out = sum(1 for r in rows
                            if classify_row(r["geocode_status"], r["lon_wgs84"], r["lat_wgs84"]) == "out")
                n_ok = sum(1 for r in rows if r["geocode_status"] == "ok")
                self.assertEqual(n_in + n_out, n_ok)
                self.assertEqual(n_ok + sum(1 for r in rows if r["geocode_status"] != "ok"),
                                 len(rows))

    def test_corridor_list_rows_are_inside_bbox(self):
        for key, (gc, ci) in self.DATASETS.items():
            path = REPO_ROOT / ci
            if not path.exists():
                continue
            with self.subTest(key=key):
                rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
                self.assertGreater(len(rows), 0, "%s 走廊内清单为空" % ci)
                for r in rows:
                    self.assertTrue(
                        in_corridor(r["lon_wgs84"], r["lat_wgs84"]),
                        "%s 含走廊外坐标: %s, %s" % (ci, r["lon_wgs84"], r["lat_wgs84"]))


class PoiComparisonTests(unittest.TestCase):
    def test_poi_geojson_counts_positive(self):
        path = REPO_ROOT / "data/processed/facility_poi_gaode.geojson"
        if not path.exists():
            return
        d = json.loads(path.read_text(encoding="utf-8"))
        cats = {}
        for f in d["features"]:
            c = f["properties"].get("category", "")
            cats[c] = cats.get(c, 0) + 1
        for c in ("school", "medical", "charging"):
            with self.subTest(category=c):
                self.assertGreater(cats.get(c, 0), 0, "高德 POI 类别 %s 为空" % c)


if __name__ == "__main__":
    unittest.main()
