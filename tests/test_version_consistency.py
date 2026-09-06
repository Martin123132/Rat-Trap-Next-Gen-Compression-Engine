import re
import unittest
from pathlib import Path

from rat_trap.repository_engine import WRITER_VERSION as REPOSITORY_WRITER_VERSION
from rat_trap.sealed_file import WRITER_VERSION as SEALED_FILE_WRITER_VERSION
from rat_trap.secure_engine import WRITER_VERSION as SECURE_WRITER_VERSION
from rat_trap.windows_app import APP_VERSION


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "5.7.0"


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
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        build_script = (REPOSITORY_ROOT / "build_windows.ps1").read_text(
            encoding="utf-8"
        )
        requirements = (
            REPOSITORY_ROOT / "requirements-build-5.7.0.txt"
        ).read_text(encoding="utf-8")
        msix_script = (
            REPOSITORY_ROOT
            / "scripts"
            / "build_msix_5_5_0.ps1"
        ).read_text(encoding="utf-8")
        company_msix_script = (
            REPOSITORY_ROOT
            / "scripts"
            / "build_msix_5_7_0.ps1"
        ).read_text(encoding="utf-8")
        msix_manifest = (
            REPOSITORY_ROOT
            / "packaging"
            / "msix"
            / "AppxManifest.template.xml"
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
        self.assertEqual(SEALED_FILE_WRITER_VERSION, EXPECTED_VERSION)
        self.assertEqual(SECURE_WRITER_VERSION, EXPECTED_VERSION)
        self.assertIn("filevers=(5, 7, 0, 0)", resource)
        self.assertIn("prodvers=(5, 7, 0, 0)", resource)
        self.assertIn("FileVersion', u'5.7.0'", resource)
        self.assertIn("ProductVersion', u'5.7.0'", resource)
        self.assertIn("CompanyName', u'TWO HANDS NETWORK LTD'", resource)
        self.assertTrue(
            windows_readme.startswith("RAT-TRAP 5.7.0 FOR WINDOWS")
        )
        self.assertTrue(readme.startswith("# Rat-Trap 5.7"))
        self.assertIn("requirements-build-5.7.0.txt", build_script)
        self.assertIn('dist\\5.7.0', build_script)
        self.assertIn("packaging\\branding\\rat-trap.ico", build_script)
        self.assertIn("cryptography==49.0.0", requirements)
        self.assertIn("cffi==2.1.0", requirements)
        self.assertIn("pycparser==3.0", requirements)
        self.assertIn('$PackageVersion = "5.5.0.0"', msix_script)
        self.assertIn(
            'PackageVersion = "5.7.0.0"',
            company_msix_script,
        )
        self.assertIn(
            '"packaging\\publisher-profile.json"',
            company_msix_script,
        )
        self.assertIn("$packageFileName =", msix_script)
        self.assertNotIn(
            '$packageName = "Rat-Trap-Windows-',
            msix_script,
        )
        self.assertIn(
            "$verifiedIdentity.Name -cne $PackageName",
            msix_script,
        )
        self.assertIn(".rat-trap-msix-package-", msix_script)
        self.assertLess(
            msix_script.index("& $makeAppx unpack"),
            msix_script.index(
                "Move-Item -LiteralPath $workingPackagePath"
            ),
        )
        self.assertNotIn(
            "& $makeAppx pack /d $stageRoot /p $packagePath",
            msix_script,
        )
        self.assertIn('"THIRD-PARTY-LICENSES"', msix_script)
        self.assertIn('"SBOM"', msix_script)
        self.assertIn('"THIRD-PARTY-NOTICES.md"', msix_script)
        self.assertIn(
            "Required third-party licence is missing",
            msix_script,
        )
        self.assertIn("Required SBOM is missing", msix_script)
        self.assertIn("uap10:PackageIntegrity", msix_manifest)
        self.assertIn("--open-sealed", msix_manifest)
        self.assertIn("--open-archive", msix_manifest)
        self.assertNotIn(".rtrk</uap:FileType>", msix_manifest)
        self.assertIn("cryptography | 49.0.0", third_party)
        self.assertIn("Windows release ZIP and MSIX", third_party)
        self.assertTrue(
            third_party.startswith(
                "# Rat-Trap 5.7.0 third-party notices"
            )
        )


if __name__ == "__main__":
    unittest.main()
