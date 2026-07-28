import re
import unittest
from pathlib import Path

from rat_trap.windows_app import APP_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "5.1.1"


class VersionConsistencyTests(unittest.TestCase):
    def test_release_version_is_consistent(self) -> None:
        pyproject = (REPOSITORY_ROOT / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        resource = (
            REPOSITORY_ROOT / "packaging" / "windows_version_info.txt"
        ).read_text(encoding="utf-8")
        windows_readme = (REPOSITORY_ROOT / "README-WINDOWS.txt").read_text(
            encoding="utf-8"
        )
        build_script = (REPOSITORY_ROOT / "build_windows.ps1").read_text(
            encoding="utf-8"
        )

        project_version = re.search(
            r'(?m)^version = "([^"]+)"$', pyproject
        )
        self.assertIsNotNone(project_version)
        self.assertEqual(project_version.group(1), EXPECTED_VERSION)
        self.assertEqual(APP_VERSION, EXPECTED_VERSION)
        self.assertIn("filevers=(5, 1, 1, 0)", resource)
        self.assertIn("prodvers=(5, 1, 1, 0)", resource)
        self.assertIn("FileVersion', u'5.1.1'", resource)
        self.assertIn("ProductVersion', u'5.1.1'", resource)
        self.assertTrue(
            windows_readme.startswith("RAT-TRAP 5.1.1 FOR WINDOWS")
        )
        self.assertIn("requirements-build-5.1.1.txt", build_script)
        self.assertIn('dist\\5.1.1', build_script)


if __name__ == "__main__":
    unittest.main()
