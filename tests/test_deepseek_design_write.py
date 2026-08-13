"""Regression tests for scripts/deepseek_design.py write path hardening (issue A-1).

The model-returned `files` dict must be constrained to a whitelist:
- allowed top-level dirs: geometry/ assets/ report/ visual/
- allowed root files: proposal.md metrics.json
- absolute paths, `..` traversal, and anything else must be blocked.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from deepseek_design import (  # noqa: E402
    ALLOWED_ROOT_FILES,
    ALLOWED_TOP_LEVEL_DIRS,
    _safe_relative_path,
    write_submission,
)


class SafeRelativePathTests(unittest.TestCase):
    def test_allowed_paths(self) -> None:
        allowed = [
            "geometry/key_areas.geojson",
            "geometry/site_boundary.geojson",
            "assets/fig.png",
            "report/narrative.md",
            "visual/index.html",
            "proposal.md",
            "metrics.json",
        ]
        for path in allowed:
            with self.subTest(path=path):
                self.assertIsNotNone(_safe_relative_path(path))

    def test_traversal_and_absolute_blocked(self) -> None:
        blocked = [
            "../etc/passwd",
            "geometry/../../evil.sh",
            "/abs/path",
            "~/x.md",
            "a/./b",
            "",
            ".",
        ]
        for path in blocked:
            with self.subTest(path=path):
                self.assertIsNone(_safe_relative_path(path))

    def test_non_whitelisted_blocked(self) -> None:
        blocked = [
            "manifest.json",  # root file outside whitelist
            "other/thing.json",  # top-level dir outside whitelist
            "geometry",  # bare dir segment is not a file
        ]
        for path in blocked:
            with self.subTest(path=path):
                self.assertIsNone(_safe_relative_path(path))


class WriteSubmissionTests(unittest.TestCase):
    def test_writes_whitelist_and_blocks_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            submission = Path(tmp)
            data = {
                "files": {
                    "geometry/key_areas.geojson": {"type": "FeatureCollection", "features": []},
                    "proposal.md": "# 测试\n",
                    "../escape.txt": "evil",
                    "/etc/evil.txt": "evil",
                    "manifest.json": "tamper",
                }
            }
            write_submission(data, submission)
            self.assertTrue((submission / "geometry" / "key_areas.geojson").is_file())
            self.assertTrue((submission / "proposal.md").is_file())
            self.assertFalse((submission / "escape.txt").exists())
            self.assertFalse(Path("/etc/evil.txt").exists())
            self.assertFalse((submission / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
