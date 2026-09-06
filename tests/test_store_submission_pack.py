import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SUBMISSION_ROOT = REPOSITORY_ROOT / "store" / "submission"
LISTING_ROOT = SUBMISSION_ROOT / "en-gb"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class StoreSubmissionPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = _load_json(
            SUBMISSION_ROOT / "submission-profile.json"
        )
        self.listing = _load_json(LISTING_ROOT / "listing.json")
        self.captions = _load_json(
            LISTING_ROOT / "screenshot-captions.json"
        )

    def test_submission_remains_a_draft_with_no_invented_urls(self) -> None:
        self.assertEqual(
            self.profile["status"],
            "draft_pending_partner_center_verification",
        )
        self.assertEqual(self.profile["owner"], "TWO HANDS NETWORK LTD")
        self.assertEqual(self.profile["version"], "5.7.0")
        self.assertEqual(
            self.profile["classification"]["category"],
            "Utilities + tools",
        )
        self.assertEqual(
            self.profile["classification"]["subcategory"],
            "Backup + manage",
        )
        self.assertEqual(
            self.listing["category"],
            self.profile["classification"]["category"],
        )
        self.assertEqual(
            self.listing["subcategory"],
            self.profile["classification"]["subcategory"],
        )
        contacts = self.profile["contacts"]
        self.assertIsNone(contacts["privacy_url"])
        self.assertIsNone(contacts["support_url"])
        self.assertIsNone(contacts["website_url"])
        self.assertEqual(
            contacts["url_status"],
            "pending_company_approved_public_HTTPS_location",
        )
        self.assertTrue(
            self.profile["partner_center"]["do_not_guess_identity"]
        )

    def test_listing_fields_fit_store_limits(self) -> None:
        self.assertEqual(self.listing["language"], "en-GB")
        self.assertLessEqual(len(self.listing["short_description"]), 270)
        self.assertGreater(len(self.listing["description"]), 0)
        self.assertLessEqual(len(self.listing["description"]), 10_000)
        self.assertLessEqual(len(self.listing["features"]), 20)
        self.assertTrue(self.listing["features"])
        for feature in self.listing["features"]:
            self.assertLessEqual(len(feature), 200, feature)
        self.assertLessEqual(len(self.listing["search_terms"]), 7)
        for term in self.listing["search_terms"]:
            self.assertLessEqual(len(term), 40, term)
        unique_keyword_words = {
            word.casefold()
            for term in self.listing["search_terms"]
            for word in term.split()
        }
        self.assertLessEqual(len(unique_keyword_words), 21)
        self.assertIsNone(self.listing["whats_new"])

    def test_commercial_listing_does_not_smuggle_in_benchmark_claims(self) -> None:
        commercial_text = " ".join(
            [
                self.listing["short_description"],
                self.listing["description"],
                *self.listing["features"],
            ]
        ).casefold()
        for forbidden in (
            "7-zip",
            "winrar",
            "peazip",
            "nanazip",
            "faster than",
            "benchmark",
            "93x",
            "93×",
        ):
            self.assertNotIn(forbidden, commercial_text)
        self.assertFalse(self.listing["benchmark_numbers_used"])
        self.assertFalse(self.listing["competitor_names_used"])

    def test_public_readme_keeps_history_in_the_evidence_lane(self) -> None:
        readme = (REPOSITORY_ROOT / "README.md").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "93.68",
            "tar.xz",
            "Tar/Gzip (Legacy Standard)",
            "Why Rat-Trap? (The New Standard)",
            "Real-World Impact",
        ):
            self.assertNotIn(forbidden, readme)
        self.assertIn(
            "[Historical project narrative and provenance]",
            readme,
        )
        historical = (
            REPOSITORY_ROOT
            / "docs"
            / "HISTORICAL-PROJECT-NARRATIVE.md"
        )
        self.assertTrue(historical.is_file())
        history_text = historical.read_text(encoding="utf-8")
        self.assertIn("Glyn Evans", history_text)
        self.assertIn("Martin Ollett", history_text)
        self.assertIn("TWO HANDS NETWORK LTD", history_text)

    def test_privacy_policy_states_the_real_local_boundaries(self) -> None:
        policy = (REPOSITORY_ROOT / "PRIVACY.md").read_text(
            encoding="utf-8"
        )
        policy_flat = " ".join(policy.split())
        for required in (
            "does not include advertising, analytics, telemetry",
            "does not automatically transmit the files, passwords, recovery keys",
            "temporary plaintext",
            "live Rat-Trap repository is not encrypted",
            "Uninstalling Rat-Trap does not automatically delete",
            "Rat-Trap does not send support information automatically",
            "If the user chooses a network drive or other remote storage",
            "a person may ask us for access to, correction of, or deletion",
            "reasonable technical and organisational safeguards",
            "Information Commissioner's Office",
        ):
            self.assertIn(required, policy_flat)

    def test_support_policy_rejects_sensitive_diagnostics(self) -> None:
        support = (REPOSITORY_ROOT / "SUPPORT.md").read_text(
            encoding="utf-8"
        )
        for prohibited_item in (
            "passwords or password hints",
            "`.rtrk` recovery keys",
            "confidential archives or Sealed Files",
        ):
            self.assertIn(prohibited_item, support)
        self.assertIn(
            "Rat-Trap does not upload diagnostics automatically",
            support,
        )

    def test_certification_notes_explain_restricted_capability(self) -> None:
        notes = (
            SUBMISSION_ROOT / "certification-notes.txt"
        ).read_text(encoding="utf-8")
        notes_flat = " ".join(notes.split())
        self.assertLessEqual(len(notes), 2_000)
        self.assertIn("RUNFULLTRUST JUSTIFICATION", notes)
        self.assertIn("It uses runFullTrust", notes)
        self.assertIn(
            "Opening an associated .gmw or .rtsf only launches",
            notes_flat,
        )
        self.assertIn("does not request elevation", notes)
        self.assertIn("No account, login, subscription", notes)
        walkthrough = SUBMISSION_ROOT / "certification-test-walkthrough.md"
        self.assertTrue(walkthrough.is_file())
        self.assertIn(
            "Backups and history",
            walkthrough.read_text(encoding="utf-8"),
        )

    def test_additional_licence_terms_are_paste_ready(self) -> None:
        mapping = self.listing["additional_licence_terms"]
        relative_path = Path(mapping["source_file"])
        terms_path = REPOSITORY_ROOT / relative_path
        self.assertEqual(mapping["status"], "paste_ready_text")
        self.assertIsNone(mapping["public_url"])
        self.assertTrue(terms_path.is_file())
        terms = terms_path.read_text(encoding="utf-8")
        self.assertGreater(len(terms), 0)
        self.assertLessEqual(len(terms), 10_000)
        self.assertIn(
            "Required Notice: Copyright (c) 2026 TWO HANDS NETWORK LTD.",
            terms,
        )
        self.assertIn(
            "https://polyformproject.org/licenses/noncommercial/1.0.0",
            terms,
        )
        self.assertIn("No Liability", terms)

    def test_five_clean_screenshots_are_explicitly_pending(self) -> None:
        screenshots = self.captions["screenshots"]
        self.assertGreaterEqual(len(screenshots), 5)
        orders = [item["order"] for item in screenshots]
        files = [item["file"] for item in screenshots]
        self.assertEqual(orders, list(range(1, len(screenshots) + 1)))
        self.assertEqual(len(files), len(set(files)))
        for item in screenshots:
            self.assertLessEqual(len(item["caption"]), 200)
            self.assertEqual(item["status"], "pending_clean_capture")
            self.assertTrue(item["file"].endswith(".png"))
        secure_caption = screenshots[1]["caption"]
        self.assertIn("independent encrypted Sealed Files", secure_caption)
        self.assertIn("each with its own", secure_caption)
        self.assertNotIn("complete folder", secure_caption)

    def test_demo_data_is_fictional_and_contains_no_credentials(self) -> None:
        demo_root = REPOSITORY_ROOT / "store" / "demo-data"
        files = [path for path in demo_root.rglob("*") if path.is_file()]
        self.assertGreaterEqual(len(files), 3)
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in files
        ).casefold()
        self.assertIn("fictional, non-confidential", combined)
        self.assertNotIn("password", combined)
        self.assertNotIn("@", combined)


if __name__ == "__main__":
    unittest.main()
