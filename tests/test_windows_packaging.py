import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "packaging"
    / "msix"
    / "AppxManifest.template.xml"
)

FOUNDATION = (
    "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
)
UAP = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
UAP3 = "http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
UAP10 = "http://schemas.microsoft.com/appx/manifest/uap/windows10/10"
RESTRICTED = (
    "http://schemas.microsoft.com/appx/manifest/"
    "foundation/windows10/restrictedcapabilities"
)

NS = {
    "f": FOUNDATION,
    "uap": UAP,
    "uap3": UAP3,
    "uap10": UAP10,
    "rescap": RESTRICTED,
}

EXPECTED_ASSOCIATIONS = {
    "rattrapsealed": {
        "extension": ".rtsf",
        "content_type": "application/vnd.rat-trap.sealed",
        "parameters": '--open-sealed "%1"',
    },
    "rattraparchive": {
        "extension": ".gmw",
        "content_type": "application/vnd.rat-trap.gmw",
        "parameters": '--open-archive "%1"',
    },
}


def _qualified(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class WindowsPackagingManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = ET.parse(MANIFEST_PATH).getroot()

    def test_classic_application_entry_point_is_exact(self) -> None:
        applications = self.root.findall("./f:Applications/f:Application", NS)
        self.assertEqual(len(applications), 1)

        application = applications[0]
        self.assertEqual(application.get("Id"), "RatTrap")
        self.assertEqual(application.get("Executable"), "Rat-Trap.exe")
        self.assertEqual(
            application.get(_qualified(UAP10, "RuntimeBehavior")),
            "packagedClassicApp",
        )
        self.assertEqual(
            application.get(_qualified(UAP10, "TrustLevel")),
            "mediumIL",
        )
        self.assertNotIn("EntryPoint", application.attrib)
        self.assertNotIn("StartPage", application.attrib)

    def test_file_associations_are_exact_and_safe(self) -> None:
        association_extensions = [
            element
            for element in self.root.iter()
            if _local_name(element.tag) == "Extension"
            and element.get("Category") == "windows.fileTypeAssociation"
        ]
        self.assertEqual(len(association_extensions), 2)
        self.assertTrue(
            all(
                element.tag == _qualified(UAP3, "Extension")
                for element in association_extensions
            )
        )

        every_association = [
            element
            for element in self.root.iter()
            if _local_name(element.tag) == "FileTypeAssociation"
        ]
        self.assertEqual(len(every_association), 2)
        self.assertTrue(
            all(
                element.tag == _qualified(UAP3, "FileTypeAssociation")
                for element in every_association
            )
        )

        associations = []
        for extension in association_extensions:
            self.assertIsNone(extension.get("Executable"))
            self.assertIsNone(extension.get("EntryPoint"))
            children = extension.findall("./uap3:FileTypeAssociation", NS)
            self.assertEqual(len(children), 1)
            associations.extend(children)

        self.assertEqual(
            {association.get("Name") for association in associations},
            set(EXPECTED_ASSOCIATIONS),
        )

        all_registered_types = set()
        for association in associations:
            expected = EXPECTED_ASSOCIATIONS[association.get("Name")]
            self.assertEqual(
                association.tag,
                _qualified(UAP3, "FileTypeAssociation"),
            )
            self.assertEqual(
                association.get("Parameters"),
                expected["parameters"],
            )
            self.assertEqual(association.get("MultiSelectModel"), "Single")
            self.assertIsNone(association.get("Executable"))
            self.assertIsNone(association.get("EntryPoint"))

            command_elements = {
                _local_name(element.tag)
                for element in association.iter()
                if _local_name(element.tag) in {"SupportedVerbs", "Verb"}
            }
            self.assertEqual(command_elements, set())

            file_types = association.findall(
                "./uap:SupportedFileTypes/uap:FileType",
                NS,
            )
            self.assertEqual(len(file_types), 1)
            file_type = file_types[0]
            self.assertEqual(file_type.tag, _qualified(UAP, "FileType"))
            self.assertEqual(file_type.text, expected["extension"])
            self.assertEqual(
                file_type.get("ContentType"),
                expected["content_type"],
            )
            all_registered_types.add(file_type.text)

        self.assertEqual(all_registered_types, {".gmw", ".rtsf"})
        self.assertNotIn(".rtrk", all_registered_types)

        every_file_type = [
            element
            for element in self.root.iter()
            if _local_name(element.tag) == "FileType"
        ]
        self.assertEqual(len(every_file_type), 2)
        self.assertTrue(
            all(
                element.tag == _qualified(UAP, "FileType")
                for element in every_file_type
            )
        )

    def test_run_full_trust_uses_restricted_capability_namespace(self) -> None:
        capabilities = [
            element
            for element in self.root.iter()
            if _local_name(element.tag) == "Capability"
        ]
        self.assertEqual(len(capabilities), 1)
        self.assertEqual(capabilities[0].get("Name"), "runFullTrust")
        self.assertEqual(
            capabilities[0].tag,
            _qualified(RESTRICTED, "Capability"),
        )
        self.assertIsNotNone(
            self.root.find(
                "./f:Capabilities/rescap:Capability"
                "[@Name='runFullTrust']",
                NS,
            )
        )

    def test_every_referenced_visual_asset_exists(self) -> None:
        references = set()
        for element in self.root.iter():
            for attribute, value in element.attrib.items():
                if _local_name(attribute).lower().endswith("logo"):
                    references.add(value)
            if _local_name(element.tag) == "Logo" and element.text:
                references.add(element.text)

        self.assertEqual(
            references,
            {
                r"Assets\GMW.png",
                r"Assets\RTSF.png",
                r"Assets\Square44x44Logo.png",
                r"Assets\Square150x150Logo.png",
                r"Assets\StoreLogo.png",
            },
        )
        for relative in references:
            with self.subTest(asset=relative):
                parts = relative.replace("\\", "/").split("/")
                self.assertNotIn("..", parts)
                self.assertTrue(
                    (MANIFEST_PATH.parent.joinpath(*parts)).is_file()
                )


if __name__ == "__main__":
    unittest.main()
