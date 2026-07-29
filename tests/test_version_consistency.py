import re
import unittest
from pathlib import Path

from rat_trap.repository_engine import WRITER_VERSION as REPOSITORY_WRITER_VERSION
from rat_trap.secure_engine import WRITER_VERSION as SECURE_WRITER_VERSION
from rat_trap.windows_app import APP_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "5.3.0"


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
        requirements = (
            REPOSITORY_ROOT / "requirements-build-5.3.0.txt"
        ).read_text(encoding="utf-8")
        package_script = (
            REPOSITORY_ROOT
            / "scripts"
            / "package_windows_release_5_3_0.ps1"
        ).read_text(encoding="utf-8")
        third_party = (
            REPOSITORY_ROOT / "THIRD-PARTY-NOTICES.md"
        ).read_text(encoding="utf-8")

        project_version = re.search(
            r'(?m)^version = "([^"]+)"$', pyproject
        )
        self.assertIsNotNone(project_version)
        self.assertEqual(project_version.group(1), EXPECTED_VERSION)
        self.assertIn('license = { file = "LICENSE.md" }', pyproject)
        self.assertEqual(APP_VERSION, EXPECTED_VERSION)
        self.assertEqual(REPOSITORY_WRITER_VERSION, EXPECTED_VERSION)
        self.assertEqual(SECURE_WRITER_VERSION, EXPECTED_VERSION)
        self.assertIn("filevers=(5, 3, 0, 0)", resource)
        self.assertIn("prodvers=(5, 3, 0, 0)", resource)
        self.assertIn("FileVersion', u'5.3.0'", resource)
        self.assertIn("ProductVersion', u'5.3.0'", resource)
        self.assertTrue(
            windows_readme.startswith("RAT-TRAP 5.3.0 FOR WINDOWS")
        )
        self.assertIn("requirements-build-5.3.0.txt", build_script)
        self.assertIn('dist\\5.3.0', build_script)
        self.assertIn("cryptography==49.0.0", requirements)
        self.assertIn("cffi==2.1.0", requirements)
        self.assertIn("pycparser==3.0", requirements)
        self.assertIn('$version = "5.3.0"', package_script)
        self.assertIn("SECURE-ARCHIVE-FORMAT.md", package_script)
        self.assertIn("cryptography | 49.0.0", third_party)


if __name__ == "__main__":
    unittest.main()
