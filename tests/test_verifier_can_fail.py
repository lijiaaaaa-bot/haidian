"""Reverse-injection tests: prove the spatial/metric CODE checks can actually fail.

Every check here once reported PASS on a package that was visibly broken:

  - the coverage and overlap checks measured areas in EPSG:4326 degrees but
    compared them against an absolute `1.0` threshold. At Beijing's latitude
    1 deg² is roughly 9,492 km², so no real site could ever reach it and both
    critical checks were unreachable.
  - the within-boundary check derived a filename from each layer name
    (BUILDING_FOOTPRINT -> building_footprint.geojson) and `continue`d when the
    file was absent. Packages ship buildings.geojson, so most layers were never
    examined and out-of-boundary features passed silently.
  - nothing compared metrics.json against the submitted geometry, so a declared
    ratio could be double what the geometry supports.

Each test injects one known defect into an otherwise clean package and asserts
the corresponding check reports FAIL. A test that goes green after someone
reverts the projection or restores the silent `continue` is the point: these are
the regression guards the verifier never had.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

HAS_SPATIAL_DEPS = all(
    importlib.util.find_spec(name) is not None for name in ["shapely", "pyproj"]
)

from constraints.engine import (  # noqa: E402
    CheckOutcome,
    ConstraintEngine,
    _check_features_within_boundary,
    _check_land_use_coverage,
    _check_no_land_use_overlap,
)

if HAS_SPATIAL_DEPS:
    from constraints.geometry_consistency import (  # noqa: E402
        check_metric_matches_geometry,
    )

# A ~0.95 km² site near Beijing, in the EPSG:4326 exchange CRS the packages use.
WEST, EAST = 116.34, 116.35
SOUTH, NORTH = 39.99, 40.00
MID = 116.345

EDITABLE_LAYERS = [
    "LAND_USE", "PARCEL", "BUILDING_FOOTPRINT", "ROAD_CENTERLINE", "ROAD_AREA",
    "GREEN_SPACE", "PUBLIC_SPACE", "PHASE", "AI_SERVICE_ZONE", "SCENARIO_NODE",
]


def box(west: float, east: float, south: float, north: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south],
        ]],
    }


def feature(feature_id: str, layer: str, geometry: dict, **props) -> dict:
    return {
        "type": "Feature",
        "properties": {"id": feature_id, "layer": layer, **props},
        "geometry": geometry,
    }


def collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


class SpatialCheckInjectionTest(unittest.TestCase):
    """One clean package per test, then one injected defect."""

    def setUp(self) -> None:
        if not HAS_SPATIAL_DEPS:
            self.skipTest("shapely/pyproj required — these checks must not be skipped in CI")
        self._tmp = tempfile.TemporaryDirectory()
        self.sub = Path(self._tmp.name) / "submission"
        (self.sub / "geometry").mkdir(parents=True)
        self.write_layer("site_boundary", collection(
            feature("SITE-001", "SITE_BOUNDARY", box(WEST, EAST, SOUTH, NORTH)),
        ))
        self.write_layer("land_use", collection(
            feature("LU-001", "LAND_USE", box(WEST, MID, SOUTH, NORTH)),
            feature("LU-002", "LAND_USE", box(MID, EAST, SOUTH, NORTH)),
        ))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_layer(self, name: str, data: dict) -> None:
        path = self.sub / "geometry" / f"{name}.geojson"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def write_metrics(self, metrics: dict) -> None:
        (self.sub / "metrics.json").write_text(
            json.dumps({"schema_version": "1.0", "metrics": metrics}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_clean_package_passes_all_spatial_checks(self):
        """Guards against over-correction: a correct package must still pass."""
        for check in (_check_land_use_coverage, _check_no_land_use_overlap):
            outcome, detail, _ = check(self.sub, {})
            self.assertEqual(outcome, CheckOutcome.PASS, f"{check.__name__}: {detail}")

        outcome, detail, _ = _check_features_within_boundary(
            self.sub, {"generated_layers": EDITABLE_LAYERS}
        )
        self.assertEqual(outcome, CheckOutcome.PASS, detail)

    def test_coverage_gap_is_detected(self):
        self.write_layer("land_use", collection(
            feature("LU-001", "LAND_USE", box(WEST, MID, SOUTH, NORTH)),
            feature("LU-002", "LAND_USE", box(MID + 0.0015, EAST, SOUTH, NORTH)),
        ))
        outcome, detail, evidence = _check_land_use_coverage(self.sub, {})
        self.assertEqual(outcome, CheckOutcome.FAIL, detail)
        self.assertIn("未完全覆盖", detail)
        gap_sqm = float(evidence.split("gap area ")[1].split(" m²")[0])
        self.assertGreater(gap_sqm, 50_000, "gap looks like it was measured in degrees")
        self.assertLess(gap_sqm, 300_000)

    def test_gap_far_below_one_square_degree_still_fails(self):
        """The exact regression: any real-world gap is a tiny number of deg²."""
        self.write_layer("land_use", collection(
            feature("LU-001", "LAND_USE", box(WEST, MID, SOUTH, NORTH)),
        ))
        from shapely.geometry import shape

        raw_gap_deg2 = shape(box(MID, EAST, SOUTH, NORTH)).area
        self.assertLess(raw_gap_deg2, 1.0, "fixture invalid — gap must be under 1 deg²")

        outcome, _, _ = _check_land_use_coverage(self.sub, {})
        self.assertEqual(
            outcome, CheckOutcome.FAIL,
            "half the site is unassigned; a deg²-vs-m² threshold would call this PASS",
        )

    def test_land_use_overlap_is_detected(self):
        self.write_layer("land_use", collection(
            feature("LU-001", "LAND_USE", box(WEST, MID, SOUTH, NORTH)),
            feature("LU-002", "LAND_USE", box(MID - 0.0015, EAST, SOUTH, NORTH)),
        ))
        outcome, detail, _ = _check_no_land_use_overlap(self.sub, {})
        self.assertEqual(outcome, CheckOutcome.FAIL, detail)
        self.assertIn("LU-001 ∩ LU-002", detail)

    def test_feature_outside_boundary_is_detected_under_canonical_filename(self):
        """BUILDING_FOOTPRINT ships as buildings.geojson — the silent-skip case."""
        self.write_layer("buildings", collection(
            feature("BLD-001", "BUILDING_FOOTPRINT",
                    box(EAST + 0.001, EAST + 0.002, SOUTH, SOUTH + 0.001)),
        ))
        outcome, detail, _ = _check_features_within_boundary(
            self.sub, {"generated_layers": EDITABLE_LAYERS}
        )
        self.assertEqual(outcome, CheckOutcome.FAIL, detail)
        self.assertIn("BLD-001", detail)

    def test_out_of_boundary_line_is_detected(self):
        self.write_layer("roads", collection(
            feature("RD-001", "ROAD_CENTERLINE", {
                "type": "LineString",
                "coordinates": [[EAST + 0.001, SOUTH], [EAST + 0.003, NORTH]],
            }),
        ))
        outcome, detail, _ = _check_features_within_boundary(
            self.sub, {"generated_layers": EDITABLE_LAYERS}
        )
        self.assertEqual(outcome, CheckOutcome.FAIL, detail)
        self.assertIn("RD-001", detail)

    def test_no_matching_features_is_a_failure_not_a_pass(self):
        (self.sub / "geometry" / "land_use.geojson").unlink()
        outcome, detail, _ = _check_features_within_boundary(
            self.sub, {"generated_layers": EDITABLE_LAYERS}
        )
        self.assertEqual(outcome, CheckOutcome.FAIL, detail)
        self.assertIn("没有任何 feature 被检查", detail)

    def test_declared_green_ratio_matching_geometry_passes(self):
        self.write_layer("green_space", collection(
            feature("GS-001", "GREEN_SPACE", box(WEST, WEST + 0.001, SOUTH, NORTH)),
        ))
        from constraints.geometry_consistency import _layer_geometries, _union_area

        site = _union_area(_layer_geometries(self.sub, "SITE_BOUNDARY"))
        green = _union_area(_layer_geometries(self.sub, "GREEN_SPACE"))
        self.write_metrics({"green_ratio": round(green / site, 6)})

        outcome, detail, _ = check_metric_matches_geometry(self.sub, {
            "metric_key": "green_ratio", "source": "layer_ratio",
            "layer": "GREEN_SPACE", "tolerance_pct": 5.0,
        })
        self.assertEqual(outcome, CheckOutcome.PASS, detail)

    def test_inflated_green_ratio_is_detected(self):
        self.write_layer("green_space", collection(
            feature("GS-001", "GREEN_SPACE", box(WEST, WEST + 0.001, SOUTH, NORTH)),
        ))
        from constraints.geometry_consistency import _layer_geometries, _union_area

        site = _union_area(_layer_geometries(self.sub, "SITE_BOUNDARY"))
        green = _union_area(_layer_geometries(self.sub, "GREEN_SPACE"))
        self.write_metrics({"green_ratio": round(green / site * 2.1, 6)})

        outcome, detail, _ = check_metric_matches_geometry(self.sub, {
            "metric_key": "green_ratio", "source": "layer_ratio",
            "layer": "GREEN_SPACE", "tolerance_pct": 5.0,
        })
        self.assertEqual(outcome, CheckOutcome.FAIL, detail)
        self.assertIn("不符", detail)

    def test_overlapping_green_space_is_not_double_counted(self):
        self.write_layer("green_space", collection(
            feature("GS-001", "GREEN_SPACE", box(WEST, WEST + 0.001, SOUTH, NORTH)),
            feature("GS-002", "GREEN_SPACE", box(WEST, WEST + 0.001, SOUTH, NORTH)),
        ))
        from constraints.geometry_consistency import _layer_geometries, _union_area

        site = _union_area(_layer_geometries(self.sub, "SITE_BOUNDARY"))
        one_tile = _union_area([_layer_geometries(self.sub, "GREEN_SPACE")[0]])
        self.write_metrics({"green_ratio": round(one_tile / site * 2, 6)})

        outcome, detail, _ = check_metric_matches_geometry(self.sub, {
            "metric_key": "green_ratio", "source": "layer_ratio",
            "layer": "GREEN_SPACE", "tolerance_pct": 5.0,
        })
        self.assertEqual(outcome, CheckOutcome.FAIL, detail)

    def test_absent_metric_skips_rather_than_passes(self):
        self.write_layer("green_space", collection(
            feature("GS-001", "GREEN_SPACE", box(WEST, WEST + 0.001, SOUTH, NORTH)),
        ))
        self.write_metrics({"site_area_sqm": 947000})
        outcome, _, _ = check_metric_matches_geometry(self.sub, {
            "metric_key": "green_ratio", "source": "layer_ratio",
            "layer": "GREEN_SPACE", "tolerance_pct": 5.0,
        })
        self.assertEqual(outcome, CheckOutcome.SKIP)


class RegistryWiringTest(unittest.TestCase):
    """The consistency checks are worthless if the loop never runs them."""

    def test_consistency_constraints_are_registered_and_executable(self):
        engine = ConstraintEngine(str(REPO_ROOT))
        engine.load_registry()
        consistency = [
            c for c in engine.constraints
            if c.get("check_function") == "verify_metric_matches_geometry"
        ]
        self.assertTrue(consistency, "no declared-vs-recomputed constraints in registry.json")
        for constraint in consistency:
            self.assertTrue(constraint.get("enabled"), constraint["constraint_id"])
            self.assertEqual(constraint.get("check_type"), "CODE")
            self.assertIsNotNone(
                engine._get_checker(constraint["check_function"]),
                f"{constraint['constraint_id']} has no checker registered",
            )

    def test_registry_regeneration_is_idempotent(self):
        from constraints.extractors import ConstraintExtractor

        committed = json.loads(
            (REPO_ROOT / "constraints" / "registry.json").read_text(encoding="utf-8")
        )
        regenerated = ConstraintExtractor(str(REPO_ROOT)).generate_registry()
        self.assertEqual(
            [c["constraint_id"] for c in committed["constraints"]],
            [c["constraint_id"] for c in regenerated["constraints"]],
        )


if __name__ == "__main__":
    unittest.main()
