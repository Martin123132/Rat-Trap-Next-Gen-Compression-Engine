import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


class ExportZipTests(unittest.TestCase):
    def test_export_zip_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "input"
            src.mkdir()
            nested = src / "nested"
            nested.mkdir()

            originals = {
                Path("alpha.txt"): b"alpha-bytes\n",
                Path("nested/beta.bin"): bytes(range(64)),
                Path("nested/gamma.txt"): "hello-zip".encode("utf-8"),
            }
            for rel, data in originals.items():
                target = src / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

            archive = root / "sample.gmw"
            exported = root / "sample.zip"

            subprocess.run(
                [sys.executable, "-m", "rat_trap.cli", "compress", str(src), str(archive)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [sys.executable, "-m", "rat_trap.cli", "export-zip", str(archive), str(exported)],
                check=True,
                capture_output=True,
                text=True,
            )

            with zipfile.ZipFile(exported, "r") as zf:
                names = sorted(zf.namelist())
                self.assertEqual(names, sorted(str(p).replace('\\\\', '/') for p in originals))
                for rel, data in originals.items():
                    with zf.open(str(rel).replace('\\\\', '/')) as fp:
                        self.assertEqual(fp.read(), data)


if __name__ == "__main__":
    unittest.main()
