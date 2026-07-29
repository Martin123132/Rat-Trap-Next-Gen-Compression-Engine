import io
import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from rat_trap import gmw_tool, repository_engine


def tree_contents(folder: Path) -> dict[str, bytes | None]:
    contents: dict[str, bytes | None] = {}
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder).as_posix()
        contents[relative] = path.read_bytes() if path.is_file() else None
    return contents


class RepositoryEngineTests(unittest.TestCase):
    def test_public_api_includes_recovery_and_issue_controls(self) -> None:
        self.assertTrue(
            {
                "AbandonJobResult",
                "IncompleteJobInfo",
                "RepositoryIssue",
                "abandon_incomplete_job",
                "list_incomplete_jobs",
                "list_repository_issues",
            }.issubset(repository_engine.__all__)
        )

    def test_initialization_is_idempotent_and_empty_snapshots_need_no_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            source = root / "empty-source"
            source.mkdir()
            first_info = repository_engine.init_repository(repository)
            second_info = repository_engine.init_repository(repository)
            self.assertEqual(first_info.repository_id, second_info.repository_id)

            first = repository_engine.create_snapshot(repository, source)
            second = repository_engine.create_snapshot(repository, source)
            info = repository_engine.repository_info(repository)
            self.assertEqual(info.snapshot_count, 2)
            self.assertEqual(info.pack_count, 0)
            self.assertEqual(second.parent_snapshot_id, first.snapshot_id)
            self.assertEqual(second.new_object_count, 0)
            restored = root / "empty-restored"
            repository_engine.restore_snapshot(
                repository, first.snapshot_id, restored
            )
            self.assertEqual(list(restored.iterdir()), [])

    def test_concurrent_initializers_never_replace_the_winning_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            gate = root / "go"
            child = (
                "import sys,time\n"
                "from pathlib import Path\n"
                "from rat_trap import repository_engine as r\n"
                "repo,gate,ready=map(Path,sys.argv[1:4])\n"
                "ready.write_text('ready',encoding='utf-8')\n"
                "while not gate.exists(): time.sleep(0.001)\n"
                "try:\n"
                " info=r.init_repository(repo)\n"
                " print('OK:'+info.repository_id)\n"
                "except r.RepositoryLockedError:\n"
                " print('LOCKED')\n"
            )
            processes: list[subprocess.Popen[str]] = []
            try:
                for index in range(4):
                    ready = root / f"ready-{index}"
                    processes.append(
                        subprocess.Popen(
                            [
                                sys.executable,
                                "-c",
                                child,
                                str(repository),
                                str(gate),
                                str(ready),
                            ],
                            cwd=Path(__file__).resolve().parents[1],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                    )
                deadline = time.monotonic() + 20
                while (
                    len(list(root.glob("ready-*"))) < len(processes)
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                self.assertEqual(
                    len(list(root.glob("ready-*"))), len(processes)
                )
                gate.write_text("go", encoding="utf-8")
                outputs = [
                    process.communicate(timeout=30) for process in processes
                ]
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)

            for process, (stdout, stderr) in zip(processes, outputs):
                self.assertEqual(
                    process.returncode, 0, msg=stdout + stderr
                )
            successful_ids = {
                stdout.strip().removeprefix("OK:")
                for stdout, _ in outputs
                if stdout.strip().startswith("OK:")
            }
            final_id = json.loads(
                (repository / "repository.json").read_text(encoding="utf-8")
            )["repository_id"]
            self.assertTrue(successful_ids)
            self.assertEqual(successful_ids, {final_id})

    def test_snapshot_history_dedup_restore_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "empty").mkdir()
            repeated = (b"Rat-Trap repository data\n" * 50_000)
            (source / "first.txt").write_bytes(repeated)
            (source / "copy.txt").write_bytes(repeated)
            repository = root / "repository"

            initial = repository_engine.init_repository(repository)
            first = repository_engine.create_snapshot(
                repository, source, label="baseline"
            )
            first_tree = tree_contents(source)

            self.assertEqual(initial.snapshot_count, 0)
            self.assertEqual(first.file_count, 2)
            self.assertEqual(first.directory_count, 1)
            self.assertGreater(first.reused_bytes, 0)
            self.assertLess(first.new_object_raw_bytes, first.total_bytes)

            (source / "first.txt").write_bytes(repeated + b"changed")
            (source / "copy.txt").unlink()
            (source / "new.txt").write_text("new version", encoding="utf-8")
            second = repository_engine.create_snapshot(
                repository, source, label="after edit"
            )

            self.assertEqual(second.parent_snapshot_id, first.snapshot_id)
            self.assertEqual(second.changed_file_count, 2)
            self.assertEqual(second.deleted_file_count, 1)
            self.assertEqual(
                [item.snapshot_id for item in repository_engine.list_snapshots(repository)],
                [second.snapshot_id, first.snapshot_id],
            )
            self.assertEqual(
                {
                    item.snapshot_id
                    for item in repository_engine.search_history(
                        repository, "first.txt"
                    )
                },
                {first.snapshot_id, second.snapshot_id},
            )

            restored = root / "restored-baseline"
            result = repository_engine.restore_snapshot(
                repository, first.snapshot_id, restored
            )
            self.assertEqual(result.restored_bytes, first.total_bytes)
            self.assertEqual(tree_contents(restored), first_tree)
            verified = repository_engine.verify_repository(repository)
            self.assertTrue(verified.full_data_verified)
            self.assertEqual(verified.snapshot_count, 2)
            self.assertEqual(verified.unreferenced_object_count, 0)

    def test_storage_accounting_separates_payload_pack_and_repository_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "many-small-files"
            source.mkdir()
            for index in range(100):
                (source / f"{index:03d}.txt").write_text(
                    f"row {index}", encoding="utf-8"
                )
            repository = root / "repository"
            repository_engine.init_repository(repository)
            snapshot = repository_engine.create_snapshot(repository, source)
            pack_bytes = sum(
                path.stat().st_size
                for path in (repository / "packs").rglob("*.rtpack")
            )
            info = repository_engine.repository_info(repository)

            self.assertEqual(snapshot.new_pack_file_bytes, pack_bytes)
            self.assertLess(snapshot.new_object_payload_bytes, pack_bytes)
            self.assertEqual(info.pack_file_bytes, pack_bytes)
            self.assertEqual(
                info.object_payload_bytes,
                snapshot.new_object_payload_bytes,
            )
            self.assertGreaterEqual(info.repository_file_bytes, pack_bytes)
            self.assertEqual(info.trash_file_bytes, 0)

    def test_content_defined_chunking_reuses_shifted_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            repository = root / "repository"
            original = random.Random(42).randbytes(2 * 1024 * 1024)
            (source / "image.bin").write_bytes(original)
            repository_engine.init_repository(
                repository,
                chunk_min=4096,
                chunk_avg=16384,
                chunk_max=65536,
            )
            repository_engine.create_snapshot(repository, source)

            prefix = b"inserted-prefix" * 73
            (source / "image.bin").write_bytes(prefix + original)
            shifted = repository_engine.create_snapshot(repository, source)

            self.assertGreater(shifted.reused_bytes, len(original) * 0.9)
            self.assertLess(shifted.new_object_raw_bytes, shifted.total_bytes * 0.1)
            restored = root / "restored"
            repository_engine.restore_snapshot(
                repository, shifted.snapshot_id, restored
            )
            self.assertEqual(
                (restored / "image.bin").read_bytes(), prefix + original
            )

    def test_content_defined_chunking_reuses_shifted_low_entropy_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            repository = root / "repository"
            original = b"ABCD" * (3 * 1024 * 1024)
            (source / "repeating.bin").write_bytes(original)
            repository_engine.init_repository(repository)
            repository_engine.create_snapshot(repository, source)

            (source / "repeating.bin").write_bytes(b"X" + original)
            shifted = repository_engine.create_snapshot(repository, source)

            self.assertGreater(shifted.reused_bytes, len(original) * 0.8)
            self.assertLess(
                shifted.new_object_raw_bytes, shifted.total_bytes * 0.2
            )
            restored = root / "low-entropy-restored"
            repository_engine.restore_snapshot(
                repository, shifted.snapshot_id, restored
            )
            self.assertEqual(
                (restored / "repeating.bin").read_bytes(), b"X" + original
            )

    def test_content_defined_chunking_reuses_shifted_phased_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            repository = root / "repository"
            phase = b"A" * 4096 + b"B" * ((4 * 1024 * 1024) - 4096)
            original = phase * 3
            (source / "phased.bin").write_bytes(original)
            repository_engine.init_repository(repository)
            repository_engine.create_snapshot(repository, source)

            (source / "phased.bin").write_bytes(b"X" + original)
            shifted = repository_engine.create_snapshot(repository, source)

            self.assertGreater(shifted.reused_bytes, len(original) * 0.8)
            self.assertLess(
                shifted.new_object_raw_bytes, shifted.total_bytes * 0.2
            )
            restored = root / "phased-restored"
            repository_engine.restore_snapshot(
                repository, shifted.snapshot_id, restored
            )
            self.assertEqual(
                (restored / "phased.bin").read_bytes(), b"X" + original
            )

    def test_fastcdc_reuses_shifted_biased_binary_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            repository = root / "repository"
            random_bytes = random.Random(919).randbytes(8 * 1024 * 1024)
            original = bytearray(
                1 if value < 26 else 0 for value in random_bytes
            )
            stride = repository_engine.DEFAULT_CHUNK_MIN + 1
            for boundary in range(
                repository_engine.DEFAULT_CHUNK_MIN,
                len(original),
                stride,
            ):
                original[boundary] = 0
                original[boundary - 1] = 0
            original_bytes = bytes(original)
            (source / "biased.bin").write_bytes(original_bytes)
            repository_engine.init_repository(repository)
            repository_engine.create_snapshot(repository, source)

            (source / "biased.bin").write_bytes(b"X" + original_bytes)
            shifted = repository_engine.create_snapshot(repository, source)

            self.assertGreater(
                shifted.reused_bytes, len(original_bytes) * 0.75
            )
            self.assertLess(
                shifted.new_object_raw_bytes, shifted.total_bytes * 0.25
            )

    def test_interrupted_file_processing_resumes_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "a.txt").write_text("a" * 100_000, encoding="utf-8")
            (source / "b.txt").write_text("b" * 100_000, encoding="utf-8")
            repository = root / "repository"
            repository_engine.init_repository(repository)

            def interrupt(name: str) -> None:
                if name.startswith("after-file:"):
                    raise RuntimeError("simulated process interruption")

            with mock.patch.object(
                repository_engine, "_failpoint", side_effect=interrupt
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated"):
                    repository_engine.create_snapshot(repository, source)

            resumed = repository_engine.create_snapshot(repository, source)
            self.assertTrue(resumed.resumed)
            self.assertEqual(repository_engine.repository_info(repository).snapshot_count, 1)
            restored = root / "restored"
            repository_engine.restore_snapshot(
                repository, resumed.snapshot_id, restored
            )
            self.assertEqual(tree_contents(restored), tree_contents(source))

    def test_resumed_job_reconciles_objects_published_by_another_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_a = root / "source-a"
            source_b = root / "source-b"
            source_a.mkdir()
            source_b.mkdir()
            content = random.Random(616).randbytes(512 * 1024)
            (source_a / "data.bin").write_bytes(content)
            (source_b / "data.bin").write_bytes(content)
            repository = root / "repository"
            repository_engine.init_repository(
                repository,
                chunk_min=4096,
                chunk_avg=16384,
                chunk_max=65536,
            )

            with mock.patch.object(
                repository_engine,
                "_failpoint",
                side_effect=lambda name: (
                    (_ for _ in ()).throw(RuntimeError("pause source A"))
                    if name.startswith("after-file:")
                    else None
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "pause source A"):
                    repository_engine.create_snapshot(repository, source_a)

            snapshot_b = repository_engine.create_snapshot(repository, source_b)
            resumed_a = repository_engine.create_snapshot(repository, source_a)

            self.assertTrue(resumed_a.resumed)
            self.assertGreater(snapshot_b.new_object_count, 0)
            self.assertEqual(resumed_a.new_object_count, 0)
            self.assertEqual(resumed_a.new_object_raw_bytes, 0)
            self.assertEqual(resumed_a.new_object_payload_bytes, 0)
            self.assertEqual(resumed_a.new_pack_file_bytes, 0)
            self.assertEqual(resumed_a.reused_bytes, len(content))
            self.assertEqual(
                repository_engine.repository_info(repository).pack_count, 1
            )
            with closing(
                sqlite3.connect(repository / "catalog.sqlite3")
            ) as catalog:
                locations, distinct_objects = catalog.execute(
                    """
                    SELECT COUNT(*), COUNT(DISTINCT object_id)
                    FROM object_locations
                    """
                ).fetchone()
            self.assertEqual(locations, distinct_objects)
            for name, snapshot in (
                ("restore-a", resumed_a),
                ("restore-b", snapshot_b),
            ):
                restored = root / name
                repository_engine.restore_snapshot(
                    repository, snapshot.snapshot_id, restored
                )
                self.assertEqual((restored / "data.bin").read_bytes(), content)

    def test_published_pack_or_manifest_is_recovered_after_interruption(self) -> None:
        for failpoint in ("after-pack-publish", "after-manifest-publish"):
            with self.subTest(failpoint=failpoint):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / "source"
                    source.mkdir()
                    (source / "data.bin").write_bytes(
                        random.Random(7).randbytes(512 * 1024)
                    )
                    repository = root / "repository"
                    repository_engine.init_repository(repository)

                    def interrupt(name: str) -> None:
                        if name == failpoint:
                            raise RuntimeError("simulated publication interruption")

                    with mock.patch.object(
                        repository_engine, "_failpoint", side_effect=interrupt
                    ):
                        with self.assertRaisesRegex(RuntimeError, "publication"):
                            repository_engine.create_snapshot(repository, source)

                    recovered = repository_engine.create_snapshot(repository, source)
                    self.assertTrue(recovered.resumed)
                    info = repository_engine.repository_info(repository)
                    self.assertEqual(info.snapshot_count, 1)
                    self.assertEqual(info.pack_count, 1)
                    self.assertTrue(
                        repository_engine.verify_repository(repository).full_data_verified
                    )

    def test_corrupt_ready_manifest_is_quarantined_without_blocking_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            path = source / "data.bin"
            path.write_bytes(random.Random(31).randbytes(128 * 1024))
            repository = root / "repository"
            repository_engine.init_repository(repository)
            healthy = repository_engine.create_snapshot(repository, source)
            path.write_bytes(random.Random(32).randbytes(128 * 1024))

            with mock.patch.object(
                repository_engine,
                "_failpoint",
                side_effect=lambda name: (
                    (_ for _ in ()).throw(RuntimeError("pause publication"))
                    if name == "after-pack-publish"
                    else None
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "pause publication"):
                    repository_engine.create_snapshot(repository, source)
            job = next((repository / "staging" / "jobs").iterdir())
            (job / "manifest.ready").write_bytes(b"broken manifest")

            self.assertEqual(
                [item.snapshot_id for item in repository_engine.list_snapshots(repository)],
                [healthy.snapshot_id],
            )
            self.assertFalse(job.exists())
            self.assertTrue(any((repository / "trash").glob("incomplete-*")))
            restored = root / "healthy-after-ready-manifest"
            repository_engine.restore_snapshot(
                repository, healthy.snapshot_id, restored
            )
            self.assertEqual(
                (restored / "data.bin").read_bytes(),
                random.Random(31).randbytes(128 * 1024),
            )

    def test_corrupt_ready_pack_is_quarantined_without_blocking_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            path = source / "data.bin"
            path.write_bytes(random.Random(41).randbytes(128 * 1024))
            repository = root / "repository"
            repository_engine.init_repository(repository)
            healthy = repository_engine.create_snapshot(repository, source)
            path.write_bytes(random.Random(42).randbytes(128 * 1024))

            with mock.patch.object(
                repository_engine,
                "_finalize_job_locked",
                side_effect=RuntimeError("pause before publication"),
            ):
                with self.assertRaisesRegex(RuntimeError, "pause before"):
                    repository_engine.create_snapshot(repository, source)
            job = next((repository / "staging" / "jobs").iterdir())
            ready_pack = next(job.glob("*.rtpack"))
            ready_pack.write_bytes(b"broken pack")

            self.assertEqual(
                [item.snapshot_id for item in repository_engine.list_snapshots(repository)],
                [healthy.snapshot_id],
            )
            self.assertFalse(job.exists())
            restored = root / "healthy-after-ready-pack"
            repository_engine.restore_snapshot(
                repository, healthy.snapshot_id, restored
            )
            self.assertTrue((restored / "data.bin").is_file())

    def test_explicit_restart_abandons_unchanged_processing_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "data.bin").write_bytes(
                random.Random(51).randbytes(128 * 1024)
            )
            repository = root / "repository"
            repository_engine.init_repository(repository)

            with mock.patch.object(
                repository_engine,
                "_failpoint",
                side_effect=lambda name: (
                    (_ for _ in ()).throw(RuntimeError("pause processing"))
                    if name.startswith("after-file:")
                    else None
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "pause processing"):
                    repository_engine.create_snapshot(repository, source)
            job = next((repository / "staging" / "jobs").iterdir())
            (job / "manifest.ready").write_bytes(b"stale derived manifest")
            (job / f"{'a' * 32}.rtpack").write_bytes(b"stale derived pack")

            restarted = repository_engine.create_snapshot(
                repository, source, restart=True
            )
            self.assertFalse(restarted.resumed)
            self.assertFalse(job.exists())
            self.assertTrue(any((repository / "trash").glob("incomplete-*")))
            self.assertTrue(
                repository_engine.verify_repository(repository).full_data_verified
            )

    def test_hard_process_exit_recovers_at_each_commit_boundary(self) -> None:
        child = (
            "import os,sys\n"
            "from pathlib import Path\n"
            "from rat_trap import repository_engine as r\n"
            "target=sys.argv[3]\n"
            "def stop(name):\n"
            "    if name == target or (target == 'after-file' and "
            "name.startswith('after-file:')):\n"
            "        os._exit(77)\n"
            "r._failpoint=stop\n"
            "r.create_snapshot(Path(sys.argv[1]), Path(sys.argv[2]))\n"
        )
        for boundary in (
            "after-file",
            "after-pack-publish",
            "after-manifest-publish",
        ):
            with self.subTest(boundary=boundary):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / "source"
                    source.mkdir()
                    (source / "data.bin").write_bytes(
                        random.Random(17).randbytes(64 * 1024)
                    )
                    repository = root / "repository"
                    repository_engine.init_repository(repository)
                    crashed = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            child,
                            str(repository),
                            str(source),
                            boundary,
                        ],
                        cwd=Path(__file__).resolve().parents[1],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        crashed.returncode,
                        77,
                        msg=crashed.stdout + crashed.stderr,
                    )
                    recovered = repository_engine.create_snapshot(
                        repository, source
                    )
                    self.assertTrue(recovered.resumed)
                    self.assertEqual(
                        repository_engine.repository_info(repository).snapshot_count,
                        1,
                    )
                    self.assertTrue(
                        repository_engine.verify_repository(repository).full_data_verified
                    )

    def test_changed_interrupted_source_requires_explicit_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            path = source / "a.txt"
            path.write_text("original", encoding="utf-8")
            repository = root / "repository"
            repository_engine.init_repository(repository)

            with mock.patch.object(
                repository_engine,
                "_failpoint",
                side_effect=lambda name: (
                    (_ for _ in ()).throw(RuntimeError("stop"))
                    if name.startswith("after-file:")
                    else None
                ),
            ):
                with self.assertRaises(RuntimeError):
                    repository_engine.create_snapshot(repository, source)
            path.write_text("changed and longer", encoding="utf-8")

            with self.assertRaises(repository_engine.SourceChangedError):
                repository_engine.create_snapshot(repository, source)
            restarted = repository_engine.create_snapshot(
                repository, source, restart=True
            )
            self.assertFalse(restarted.resumed)
            self.assertTrue(any((repository / "trash").glob("incomplete-*")))

    def test_catalog_rebuild_and_payload_corruption_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "data.bin").write_bytes(
                random.Random(99).randbytes(256 * 1024)
            )
            repository = root / "repository"
            repository_engine.init_repository(repository)
            snapshot = repository_engine.create_snapshot(repository, source)

            (repository / "catalog.sqlite3").unlink()
            rebuilt = repository_engine.rebuild_catalog(repository)
            self.assertEqual(rebuilt.snapshot_count, 1)

            pack = next((repository / "packs").rglob("*.rtpack"))
            with closing(sqlite3.connect(pack)) as connection:
                connection.execute(
                    "UPDATE objects SET data = zeroblob(payload_size)"
                )
                connection.commit()

            self.assertFalse(
                repository_engine.verify_repository(
                    repository, full=False
                ).full_data_verified
            )
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "checksum"
            ):
                repository_engine.verify_repository(repository, full=True)
            with self.assertRaises(repository_engine.RepositoryError):
                repository_engine.restore_snapshot(
                    repository, snapshot.snapshot_id, root / "corrupt-restore"
                )

    def test_missing_old_pack_does_not_block_an_intact_newer_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            repository = root / "repository"
            repository_engine.init_repository(repository)

            (source / "old.bin").write_bytes(
                random.Random(501).randbytes(256 * 1024)
            )
            old = repository_engine.create_snapshot(repository, source)
            old_pack = next((repository / "packs").rglob("*.rtpack"))

            (source / "old.bin").unlink()
            (source / "new.bin").write_bytes(
                random.Random(502).randbytes(256 * 1024)
            )
            new = repository_engine.create_snapshot(repository, source)
            self.assertEqual(
                len(list((repository / "packs").rglob("*.rtpack"))), 2
            )
            old_pack.unlink()

            self.assertEqual(
                repository_engine.repository_info(repository).issue_count, 1
            )
            issues = repository_engine.list_repository_issues(repository)
            self.assertEqual(
                [(issue.kind, issue.relpath) for issue in issues],
                [
                    (
                        "snapshot-objects",
                        "manifests/"
                        + old.manifest_sha256
                        + ".rtsnap.json",
                    )
                ],
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                gmw_tool.main(["repo-issues", str(repository)])
            cli_issues = json.loads(stdout.getvalue())
            self.assertEqual(cli_issues[0]["kind"], "snapshot-objects")
            self.assertEqual(cli_issues[0]["relpath"], issues[0].relpath)
            self.assertEqual(
                [item.snapshot_id for item in repository_engine.list_snapshots(repository)],
                [new.snapshot_id, old.snapshot_id],
            )
            restored = root / "intact-newer"
            repository_engine.restore_snapshot(
                repository, new.snapshot_id, restored
            )
            self.assertEqual(tree_contents(restored), tree_contents(source))
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "missing"
            ):
                repository_engine.restore_snapshot(
                    repository, old.snapshot_id, root / "damaged-old"
                )
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "missing"
            ):
                repository_engine.verify_repository(repository, full=True)
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "integrity issue"
            ):
                repository_engine.plan_retention(
                    repository,
                    repository_engine.RetentionPolicy(0, 0, 0, 0),
                )

    def test_malformed_old_manifest_does_not_block_healthy_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            repository = root / "repository"
            repository_engine.init_repository(repository)

            (source / "old.bin").write_bytes(
                random.Random(701).randbytes(256 * 1024)
            )
            old = repository_engine.create_snapshot(repository, source)
            old_manifest = next(
                path
                for path in (repository / "manifests").glob("*.rtsnap.json")
                if json.loads(path.read_text(encoding="utf-8"))["snapshot_id"]
                == old.snapshot_id
            )
            (source / "old.bin").unlink()
            (source / "new.bin").write_bytes(
                random.Random(702).randbytes(256 * 1024)
            )
            new = repository_engine.create_snapshot(repository, source)
            old_manifest.write_bytes(b"not valid JSON")

            info = repository_engine.repository_info(repository)
            self.assertEqual(info.issue_count, 1)
            self.assertEqual(
                [item.snapshot_id for item in repository_engine.list_snapshots(repository)],
                [new.snapshot_id],
            )
            restored = root / "healthy-after-bad-manifest"
            repository_engine.restore_snapshot(
                repository, new.snapshot_id, restored
            )
            self.assertEqual(tree_contents(restored), tree_contents(source))
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "Invalid JSON"
            ):
                repository_engine.verify_repository(repository, full=False)
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "integrity issue"
            ):
                repository_engine.plan_retention(
                    repository,
                    repository_engine.RetentionPolicy(0, 0, 0, 0),
                )

    def test_malformed_old_pack_does_not_block_an_intact_newer_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            repository = root / "repository"
            repository_engine.init_repository(repository)

            (source / "old.bin").write_bytes(
                random.Random(801).randbytes(256 * 1024)
            )
            old = repository_engine.create_snapshot(repository, source)
            old_pack = next((repository / "packs").rglob("*.rtpack"))
            (source / "old.bin").unlink()
            (source / "new.bin").write_bytes(
                random.Random(802).randbytes(256 * 1024)
            )
            new = repository_engine.create_snapshot(repository, source)
            old_pack.write_bytes(b"not a SQLite pack")

            info = repository_engine.repository_info(repository)
            self.assertEqual(info.issue_count, 2)
            self.assertEqual(
                [item.snapshot_id for item in repository_engine.list_snapshots(repository)],
                [new.snapshot_id, old.snapshot_id],
            )
            restored = root / "healthy-after-bad-pack"
            repository_engine.restore_snapshot(
                repository, new.snapshot_id, restored
            )
            self.assertEqual(tree_contents(restored), tree_contents(source))
            with self.assertRaises(repository_engine.RepositoryError):
                repository_engine.restore_snapshot(
                    repository, old.snapshot_id, root / "bad-pack-restore"
                )
            with self.assertRaises(repository_engine.RepositoryError):
                repository_engine.verify_repository(repository, full=False)

    def test_new_snapshot_repairs_a_corrupt_reused_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "data.bin").write_bytes(
                random.Random(123).randbytes(256 * 1024)
            )
            repository = root / "repository"
            repository_engine.init_repository(repository)
            repository_engine.create_snapshot(repository, source)
            old_pack = next((repository / "packs").rglob("*.rtpack"))
            with closing(sqlite3.connect(old_pack)) as connection:
                connection.execute(
                    "UPDATE objects SET data = zeroblob(payload_size)"
                )
                connection.commit()

            repaired = repository_engine.create_snapshot(repository, source)
            self.assertGreater(repaired.new_object_count, 0)
            restored = root / "repaired"
            repository_engine.restore_snapshot(
                repository, repaired.snapshot_id, restored
            )
            self.assertEqual(tree_contents(restored), tree_contents(source))
            self.assertEqual(
                repository_engine.repository_info(repository).pack_count, 2
            )
            with self.assertRaises(repository_engine.RepositoryError):
                repository_engine.verify_repository(repository, full=True)

    def test_retention_is_blocked_by_an_unfinished_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            path = source / "data.txt"
            path.write_text("first", encoding="utf-8")
            repository = root / "repository"
            repository_engine.init_repository(repository)
            repository_engine.create_snapshot(repository, source)
            path.write_text("second", encoding="utf-8")

            with mock.patch.object(
                repository_engine,
                "_failpoint",
                side_effect=lambda name: (
                    (_ for _ in ()).throw(RuntimeError("stop"))
                    if name.startswith("after-file:")
                    else None
                ),
            ):
                with self.assertRaises(RuntimeError):
                    repository_engine.create_snapshot(repository, source)
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "unfinished"
            ):
                repository_engine.plan_retention(
                    repository, repository_engine.RetentionPolicy(0, 0, 0, 0)
                )
            resumed = repository_engine.create_snapshot(repository, source)
            self.assertTrue(resumed.resumed)
            repository_engine.plan_retention(
                repository, repository_engine.RetentionPolicy(0, 0, 0, 0)
            )

    def test_unavailable_source_job_can_be_explicitly_abandoned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "data.bin").write_bytes(
                random.Random(211).randbytes(128 * 1024)
            )
            repository = root / "repository"
            repository_engine.init_repository(repository)

            with mock.patch.object(
                repository_engine,
                "_failpoint",
                side_effect=lambda name: (
                    (_ for _ in ()).throw(RuntimeError("disconnect"))
                    if name.startswith("after-file:")
                    else None
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "disconnect"):
                    repository_engine.create_snapshot(repository, source)
            unavailable = root / "disconnected-source"
            source.rename(unavailable)

            jobs = repository_engine.list_incomplete_jobs(repository)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].source_path, str(source.resolve()))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                gmw_tool.main(["repo-jobs", str(repository)])
            cli_jobs = json.loads(stdout.getvalue())
            self.assertEqual(cli_jobs[0]["job_id"], jobs[0].job_id)
            self.assertEqual(cli_jobs[0]["source_path"], str(source.resolve()))
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "unfinished"
            ):
                repository_engine.plan_retention(
                    repository,
                    repository_engine.RetentionPolicy(0, 0, 0, 0),
                )
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as mismatch:
                    gmw_tool.main(
                        [
                            "repo-abandon-job",
                            str(repository),
                            jobs[0].job_id,
                            "--confirm-job-id",
                            "0" * 32,
                        ]
                    )
            self.assertEqual(mismatch.exception.code, 2)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                gmw_tool.main(
                    [
                        "repo-abandon-job",
                        str(repository),
                        jobs[0].job_id,
                        "--confirm-job-id",
                        jobs[0].job_id,
                    ]
                )
            abandoned = json.loads(stdout.getvalue())
            self.assertEqual(abandoned["job_id"], jobs[0].job_id)
            self.assertTrue(Path(abandoned["trash_path"]).is_dir())
            self.assertEqual(
                repository_engine.list_incomplete_jobs(repository), []
            )
            repository_engine.plan_retention(
                repository, repository_engine.RetentionPolicy(0, 0, 0, 0)
            )

    def test_corrupt_staging_job_is_quarantined_without_blocking_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "data.txt").write_text("valid history", encoding="utf-8")
            repository = root / "repository"
            repository_engine.init_repository(repository)
            snapshot = repository_engine.create_snapshot(repository, source)
            damaged = repository / "staging" / "jobs" / ("f" * 32)
            damaged.mkdir()
            (damaged / "work.sqlite3").write_bytes(b"not a sqlite database")

            snapshots = repository_engine.list_snapshots(repository)
            self.assertEqual([item.snapshot_id for item in snapshots], [snapshot.snapshot_id])
            self.assertFalse(damaged.exists())
            self.assertTrue(any((repository / "trash").glob("incomplete-*")))
            restored = root / "restored-after-quarantine"
            repository_engine.restore_snapshot(
                repository, snapshot.snapshot_id, restored
            )
            self.assertEqual(tree_contents(restored), tree_contents(source))

    @unittest.skipUnless(__import__("os").name == "nt", "NTFS/Windows-only")
    def test_ntfs_alternate_data_stream_is_rejected_not_silently_lost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            path = source / "data.txt"
            path.write_text("main stream", encoding="utf-8")
            Path(str(path) + ":private").write_text(
                "alternate stream", encoding="utf-8"
            )
            if not repository_engine._alternate_data_streams(path):
                self.skipTest("Temporary filesystem does not expose NTFS streams")
            repository = root / "repository"
            repository_engine.init_repository(repository)
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "alternate data streams"
            ):
                repository_engine.create_snapshot(repository, source)

    def test_hard_links_are_rejected_not_silently_expanded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            first = source / "first.bin"
            first.write_bytes(b"hard-linked content")
            try:
                os.link(first, source / "second.bin")
            except OSError as exc:
                self.skipTest(f"Filesystem cannot create hard links: {exc}")
            repository = root / "repository"
            repository_engine.init_repository(repository)
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "Hard-linked files"
            ):
                repository_engine.create_snapshot(repository, source)

    def test_efs_and_ntfs_compressed_attributes_are_rejected(self) -> None:
        checks = (
            (
                repository_engine._FILE_ATTRIBUTE_ENCRYPTED,
                "EFS-encrypted",
            ),
            (
                repository_engine._FILE_ATTRIBUTE_COMPRESSED,
                "NTFS-compressed",
            ),
        )
        for attributes, message in checks:
            with self.subTest(attributes=attributes):
                file_stat = mock.Mock(st_file_attributes=attributes)
                with self.assertRaisesRegex(
                    repository_engine.RepositoryError, message
                ):
                    repository_engine._reject_unsupported_windows_attributes(
                        Path("protected.bin"), file_stat
                    )

    @unittest.skipUnless(os.name == "nt", "NTFS/Windows-only")
    def test_ntfs_sparse_files_are_rejected_not_silently_expanded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            sparse = source / "sparse.bin"
            sparse.write_bytes(b"")
            marked = subprocess.run(
                ["fsutil", "sparse", "setflag", str(sparse)],
                check=False,
                capture_output=True,
                text=True,
            )
            if marked.returncode != 0:
                self.skipTest("Temporary filesystem cannot mark sparse files")
            with open(sparse, "r+b") as handle:
                handle.seek((8 * 1024 * 1024) - 1)
                handle.write(b"X")
            if not int(
                getattr(sparse.stat(), "st_file_attributes", 0)
            ) & 0x200:
                self.skipTest("Temporary filesystem did not retain sparse flag")
            repository = root / "repository"
            repository_engine.init_repository(repository)
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "sparse files"
            ):
                repository_engine.create_snapshot(repository, source)

    def test_restore_refuses_existing_destination_and_manifest_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "safe.txt").write_text("safe", encoding="utf-8")
            repository = root / "repository"
            repository_engine.init_repository(repository)
            snapshot = repository_engine.create_snapshot(repository, source)
            existing = root / "existing"
            existing.mkdir()

            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "must not already exist"
            ):
                repository_engine.restore_snapshot(
                    repository, snapshot.snapshot_id, existing
                )

            manifest = next((repository / "manifests").glob("*.rtsnap.json"))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["entries"][0]["path"] = "../escaped.txt"
            manifest.write_bytes(repository_engine._canonical_json(payload))
            escaped = root / "escaped.txt"
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "unsafe path"
            ):
                repository_engine.restore_snapshot(
                    repository, snapshot.snapshot_id, root / "unsafe-restore"
                )
            self.assertFalse(escaped.exists())

    def test_retention_preview_pins_and_recoverable_prune(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            repository = root / "repository"
            repository_engine.init_repository(repository)
            (source / "old.bin").write_bytes(
                random.Random(1).randbytes(128 * 1024)
            )
            old = repository_engine.create_snapshot(repository, source)
            (source / "old.bin").unlink()
            (source / "new.bin").write_bytes(
                random.Random(2).randbytes(128 * 1024)
            )
            new = repository_engine.create_snapshot(repository, source)
            policy = repository_engine.RetentionPolicy(0, 0, 0, 0)

            repository_engine.pin_snapshot(repository, old.snapshot_id)
            pinned_plan = repository_engine.plan_retention(repository, policy)
            self.assertEqual(pinned_plan.remove_snapshot_ids, ())
            repository_engine.pin_snapshot(
                repository, old.snapshot_id, pinned=False
            )

            plan = repository_engine.prune_repository(repository, policy)
            self.assertEqual(plan.remove_snapshot_ids, (old.snapshot_id,))
            self.assertGreater(plan.fully_reclaimable_pack_bytes, 0)
            self.assertEqual(repository_engine.repository_info(repository).snapshot_count, 2)

            result = repository_engine.prune_repository(
                repository,
                policy,
                apply=True,
                expected_plan_id=plan.plan_id,
            )
            self.assertTrue(result.applied)
            self.assertGreater(result.moved_to_trash_pack_bytes, 0)
            self.assertEqual(result.reclaimed_pack_bytes, 0)
            self.assertTrue(Path(result.trash_path).is_dir())
            self.assertEqual(
                [item.snapshot_id for item in repository_engine.list_snapshots(repository)],
                [new.snapshot_id],
            )
            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "not found"
            ):
                repository_engine.restore_snapshot(
                    repository, old.snapshot_id, root / "removed"
                )
            restored = root / "retained"
            repository_engine.restore_snapshot(
                repository, new.snapshot_id, restored
            )
            self.assertTrue((restored / "new.bin").is_file())

    def test_retention_labels_mixed_pack_dead_bytes_as_logical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            dead = b"A" * (32 * 1024)
            live = b"B" * (32 * 1024)
            (source / "dead.bin").write_bytes(dead)
            (source / "live.bin").write_bytes(live)
            repository = root / "repository"
            repository_engine.init_repository(repository)
            repository_engine.create_snapshot(repository, source)
            (source / "dead.bin").unlink()
            repository_engine.create_snapshot(repository, source)

            plan = repository_engine.plan_retention(
                repository, repository_engine.RetentionPolicy(0, 0, 0, 0)
            )
            self.assertEqual(plan.fully_reclaimable_pack_bytes, 0)
            self.assertEqual(
                plan.unreclaimed_dead_object_raw_bytes, len(dead)
            )

    def test_stale_retention_plan_cannot_be_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            repository = root / "repository"
            repository_engine.init_repository(repository)
            (source / "data.txt").write_text("one", encoding="utf-8")
            repository_engine.create_snapshot(repository, source)
            policy = repository_engine.RetentionPolicy(0, 0, 0, 0)
            plan = repository_engine.plan_retention(repository, policy)
            (source / "data.txt").write_text("two", encoding="utf-8")
            repository_engine.create_snapshot(repository, source)

            with self.assertRaisesRegex(
                repository_engine.RepositoryError, "changed"
            ):
                repository_engine.prune_repository(
                    repository,
                    policy,
                    apply=True,
                    expected_plan_id=plan.plan_id,
                )

    def test_portable_export_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "notes.txt").write_text(
                "portable snapshot\n" * 1000, encoding="utf-8"
            )
            repository = root / "repository"
            repository_engine.init_repository(repository)
            snapshot = repository_engine.create_snapshot(repository, source)
            archive = root / "snapshot.gmw"

            exported = repository_engine.export_snapshot(
                repository, snapshot.snapshot_id, archive
            )
            self.assertEqual(exported.archive_bytes, archive.stat().st_size)
            self.assertEqual(gmw_tool.read_metadata(archive).profile, "balanced")
            restored = root / "portable-restored"
            gmw_tool.extract_archive(archive, restored)
            self.assertEqual(tree_contents(restored), tree_contents(source))

    def test_repository_cli_json_and_prune_is_dry_run_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "data.txt").write_text("CLI", encoding="utf-8")
            repository = root / "repository"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                gmw_tool.main(["repo-init", str(repository)])
            self.assertEqual(json.loads(stdout.getvalue())["snapshot_count"], 0)

            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                gmw_tool.main(
                    [
                        "repo-snapshot",
                        str(repository),
                        str(source),
                        "--quiet",
                    ]
                )
            snapshot_id = json.loads(stdout.getvalue())["snapshot_id"]

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                gmw_tool.main(
                    [
                        "repo-prune",
                        str(repository),
                        "--keep-last",
                        "0",
                        "--keep-daily",
                        "0",
                        "--keep-weekly",
                        "0",
                        "--keep-monthly",
                        "0",
                    ]
                )
            preview = json.loads(stdout.getvalue())
            self.assertIn("plan_id", preview)
            self.assertEqual(
                repository_engine.list_snapshots(repository)[0].snapshot_id,
                snapshot_id,
            )


if __name__ == "__main__":
    unittest.main()
