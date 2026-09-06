import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UNSIGNED_MARKER = (
    "OID.2.25.311729368913984317654407730594956997722=1"
)


class PublisherIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = json.loads(
            (
                REPOSITORY_ROOT
                / "packaging"
                / "publisher-profile.json"
            ).read_text(encoding="utf-8")
        )

    def test_company_product_identity_is_explicit(self) -> None:
        product = self.profile["product"]
        distribution = self.profile["distribution"]
        self.assertEqual(product["name"], "Rat-Trap")
        self.assertEqual(product["version"], "5.7.0")
        self.assertEqual(product["owner"], "TWO HANDS NETWORK LTD")
        self.assertEqual(
            product["publisher_intent"],
            "Two Hands Network Ltd",
        )
        self.assertEqual(
            distribution["primary_channel"],
            "Microsoft Store",
        )
        self.assertEqual(distribution["package_type"], "MSIX")
        self.assertTrue(distribution["store_signing_selected"])
        self.assertFalse(
            distribution[
                "local_production_certificate_required_for_store"
            ]
        )
        self.assertTrue(
            distribution["direct_download_is_separate_signing_lane"]
        )

    def test_development_identity_cannot_be_mistaken_for_store(self) -> None:
        identity = self.profile["development_identity"]
        self.assertEqual(
            identity["name"],
            "TwoHandsNetwork.RatTrap.Development",
        )
        self.assertTrue(identity["publisher"].endswith(UNSIGNED_MARKER))
        self.assertFalse(identity["permanent"])
        self.assertFalse(identity["public_release"])

    def test_store_identity_remains_unassigned(self) -> None:
        identity = self.profile["store_identity"]
        self.assertEqual(identity["status"], "pending_partner_center")
        for field in (
            "reserved_product_name",
            "package_identity_name",
            "package_identity_publisher",
            "package_properties_publisher_display_name",
            "package_family_name",
            "publisher_id",
            "package_sid",
            "store_id",
            "product_id",
            "listing_url",
            "recorded_utc",
        ):
            self.assertIsNone(identity[field], field)

    def test_public_attribution_is_consistent(self) -> None:
        notice = (REPOSITORY_ROOT / "NOTICE.md").read_text(
            encoding="utf-8"
        )
        license_text = (REPOSITORY_ROOT / "LICENSE.md").read_text(
            encoding="utf-8"
        )
        pyproject = (REPOSITORY_ROOT / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        windows_app = (
            REPOSITORY_ROOT / "rat_trap" / "windows_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Rat-Trap is a product owned and published by "
            "TWO HANDS NETWORK LTD",
            notice,
        )
        self.assertIn("designed and built by Glyn Evans", notice)
        self.assertIn("Motion-TimeSpace work by Martin Ollett", notice)
        self.assertNotIn(
            "was created by Martin Ollett and is owned/licensed",
            notice,
        )
        self.assertIn(
            "Required Notice: Rat-Trap is a product owned and "
            "published by TWO HANDS NETWORK LTD",
            license_text,
        )
        self.assertIn('{ name = "Glyn Evans" }', pyproject)
        self.assertIn('{ name = "Martin Ollett" }', pyproject)
        self.assertIn(
            '{ name = "TWO HANDS NETWORK LTD" }',
            pyproject,
        )
        self.assertIn("Published by ", windows_app)
        self.assertIn("TWO HANDS NETWORK LTD", windows_app)

    def test_store_builder_fails_closed_on_pending_identity(self) -> None:
        builder = (
            REPOSITORY_ROOT
            / "scripts"
            / "build_msix_5_7_0.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '$identity.status -cne "assigned"',
            builder,
        )
        self.assertIn(
            "Store identity is pending.",
            builder,
        )
        self.assertIn(
            "package_identity_name",
            builder,
        )
        self.assertIn(
            "package_identity_publisher",
            builder,
        )
        self.assertIn(
            "package_properties_publisher_display_name",
            builder,
        )
        self.assertNotIn("CN=Two Hands Network Ltd\"", builder)


if __name__ == "__main__":
    unittest.main()
