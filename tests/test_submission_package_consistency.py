"""Submission package consistency tests for submissions/test/test (issue B-2).

These tests back the claims in self_check.json / manifest.json with actual
assertions over the package contents:
  1. manifest.json file list exists and sha256 hashes match disk content
  2. self_check.json results use valid enum values
  3. compliance_matrix.json assumption_ids resolve within assumptions.json
  4. proposal.md references every known metric and every required geometry layer
  5. known metric values are reproducible from geometry/*.geojson (EPSG:4548)
"""

import hashlib
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "submissions" / "test" / "test"

HAS_REVIEW_DEPS = all(
    importlib.util.find_spec(name) is not None for name in ["shapely", "pyproj"]
)

REQUIRED_DATA_REFS = {
    "geometry/site_boundary.geojson",
    "geometry/key_areas.geojson",
    "geometry/land_use.geojson",
    "geometry/buildings.geojson",
    "geometry/roads.geojson",
    "geometry/green_space.geojson",
    "geometry/public_space.geojson",
    "geometry/constraints.geojson",
    "geometry/phasing.geojson",
}

VALID_SELF_CHECK_RESULTS = {"pass", "fail", "unknown", "not_applicable"}


def load(rel: str):
    with (PACKAGE / rel).open(encoding="utf-8") as fh:
        return json.load(fh)


class ManifestConsistencyTests(unittest.TestCase):
    def test_manifest_files_exist_and_hashes_match(self) -> None:
        manifest = load("manifest.json")
        self.assertIn("files", manifest)
        for item in manifest["files"]:
            rel = item.get("path")
            with self.subTest(path=rel):
                self.assertTrue(rel)
                if rel == "manifest.json":
                    continue  # manifest 不能包含自身哈希
                target = PACKAGE / rel
                self.assertTrue(target.is_file(), f"manifest file missing: {rel}")
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                self.assertEqual(
                    item.get("sha256"), actual, f"sha256 mismatch for {rel}"
                )


class SelfCheckConsistencyTests(unittest.TestCase):
    def test_self_check_result_enum(self) -> None:
        sc = load("self_check.json")
        self.assertIn("checks", sc)
        self.assertTrue(sc["checks"], "self_check.json checks must not be empty")
        for check in sc["checks"]:
            with self.subTest(check_id=check.get("check_id")):
                self.assertIn(check.get("result"), VALID_SELF_CHECK_RESULTS)
                self.assertIn(check.get("severity"), {"blocking", "major", "minor", "info"})


class CrossReferenceConsistencyTests(unittest.TestCase):
    def test_compliance_assumption_ids_resolve(self) -> None:
        assumptions = load("assumptions.json")
        defined = {a["id"] for a in assumptions["assumptions"]}
        compliance = load("compliance_matrix.json")
        for req in compliance.get("requirements", []):
            for aid in req.get("assumption_ids", []):
                with self.subTest(requirement=req.get("requirement_id"), assumption=aid):
                    self.assertIn(aid, defined, f"dangling assumption id {aid}")

    def test_proposal_references_all_known_metrics(self) -> None:
        text = (PACKAGE / "proposal.md").read_text(encoding="utf-8")
        metrics = load("metrics.json")["metrics"]
        for name, metric in metrics.items():
            if metric.get("status") == "known":
                with self.subTest(metric=name):
                    self.assertIn(f"[metric:{name}]", text)

    def test_proposal_references_all_required_geometry_layers(self) -> None:
        text = (PACKAGE / "proposal.md").read_text(encoding="utf-8")
        for rel in REQUIRED_DATA_REFS:
            with self.subTest(ref=rel):
                self.assertRegex(text, re.escape(f"[data:{rel}#"))


@unittest.skipUnless(HAS_REVIEW_DEPS, "shapely/pyproj required")
class MetricReproducibilityTests(unittest.TestCase):
    def test_known_area_metrics_reproducible_from_geometry(self) -> None:
        from shapely.geometry import shape
        from shapely.ops import transform
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:4326", "EPSG:4548", always_xy=True)
        to_4548 = lambda geom: transform(transformer.transform, geom)  # noqa: E731

        metrics = load("metrics.json")["metrics"]

        site = json.loads((PACKAGE / "geometry/site_boundary.geojson").read_text(encoding="utf-8"))
        site_area = sum(to_4548(shape(f["geometry"])).area for f in site["features"])
        self.assertAlmostEqual(metrics["site_area_sqm"]["value"], site_area, delta=100)

        green = json.loads((PACKAGE / "geometry/green_space.geojson").read_text(encoding="utf-8"))
        green_area = sum(to_4548(shape(f["geometry"])).area for f in green["features"])
        self.assertAlmostEqual(metrics["green_space_area_sqm"]["value"], green_area, delta=100)

        public = json.loads((PACKAGE / "geometry/public_space.geojson").read_text(encoding="utf-8"))
        public_area = sum(to_4548(shape(f["geometry"])).area for f in public["features"])
        self.assertAlmostEqual(metrics["public_space_area_sqm"]["value"], public_area, delta=100)

        key_areas = json.loads((PACKAGE / "geometry/key_areas.geojson").read_text(encoding="utf-8"))
        key_area_sum = sum(to_4548(shape(f["geometry"])).area for f in key_areas["features"])
        self.assertAlmostEqual(
            metrics["key_detailed_design_area_sqm"]["value"], key_area_sum, delta=100
        )


if __name__ == "__main__":
    unittest.main()
