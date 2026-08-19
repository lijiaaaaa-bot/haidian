"""Tests for unified acceptance criteria."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

HAS_SPATIAL = all(importlib.util.find_spec(n) is not None for n in ("shapely", "pyproj"))

from scripts.acceptance import (  # noqa: E402
    AcceptanceVector,
    collect_content_failures,
    evaluate_acceptance,
)


class AcceptanceVectorTest(unittest.TestCase):
    def test_dominates_rejects_content_regression_at_same_failures(self):
        good = AcceptanceVector(10, 4, 3, 3, 30000, 12, 20, 10)
        bad = AcceptanceVector(10, 4, 3, 3, 5000, 6, 2, 10)
        self.assertTrue(good.dominates(bad))
        self.assertFalse(bad.dominates(good))

    def test_dominates_accepts_lower_failures(self):
        best = AcceptanceVector(10, 4, 3, 3, 30000, 12, 20, 10)
        better = AcceptanceVector(8, 3, 2, 3, 28000, 12, 18, 10)
        self.assertTrue(better.dominates(best))


class ContentFloorsTest(unittest.TestCase):
    def test_short_proposal_fails_content_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "s"
            sub.mkdir()
            (sub / "proposal.md").write_text("# Title\n\n## One\n", encoding="utf-8")
            failures = collect_content_failures(sub)
            ids = {f.failure_id for f in failures}
            self.assertIn("CONTENT-proposal-h2", ids)


@unittest.skipUnless(HAS_SPATIAL, "spatial deps required")
class EvaluateAcceptanceTest(unittest.TestCase):
    def test_full_acceptance_exceeds_code_only_on_test_test(self):
        sub = REPO_ROOT / "submissions/test/test"
        if not sub.is_dir():
            self.skipTest("submissions/test/test not present")
        code_failures, code_vec = evaluate_acceptance(sub, code_only=True)[0], evaluate_acceptance(sub, code_only=True)[1]
        full_failures, full_vec = evaluate_acceptance(sub)
        self.assertGreaterEqual(full_vec.total_failures, code_vec.total_failures)
        self.assertGreater(full_vec.self_check_failures, 0)


if __name__ == "__main__":
    unittest.main()
