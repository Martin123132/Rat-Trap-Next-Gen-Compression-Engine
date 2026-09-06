import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import sealed_file, secure_engine, solid_engine


PASSWORD = "Rat-Trap sealed-file test password 2026!"
NEW_PASSWORD = "Rat-Trap rotated sealed-file password 2026!"


class SealedFileTests(unittest.TestCase):
    def _seal(
        self,
        root: Path,
        *,
        name: str = "private notes.txt",
        content: bytes = b"private Rat-Trap marker\n" * 200,
    ):
        source_folder = root / "plaintext"
        source_folder.mkdir(exist_ok=True)
        source = source_folder / name
        source.write_bytes(content)
        output = root / "sealed" / sealed_file.default_sealed_name()
        recovery = root / "recovery" / f"{output.stem}.rtrk"
        result = sealed_file.seal_file(
            source,
            output,
            password=PASSWORD,
            recovery_key_output=recovery,
            allow_plaintext_temp=True,
        )
        return source, output, recovery, result

    def test_password_and_recovery_round_trip_hides_name_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output, recovery, created = self._seal(root)
            outer = output.read_bytes()

            self.assertTrue(source.is_file())
            self.assertTrue(created.source_retained)
            self.assertNotIn(source.name.encode("utf-8"), outer)
            self.assertNotIn(b"private Rat-Trap marker", outer)
            self.assertEqual(output.suffix, ".rtsf")

            locked = sealed_file.read_locked_info(output)
            self.assertTrue(locked.locked)
            self.assertIsNone(locked.original_name)
            self.assertIsNone(locked.original_size)
            self.assertIsNone(locked.profile_format)
            self.assertIsNone(locked.profile_schema_version)
            self.assertFalse(locked.profile_verified)

            password_info = sealed_file.verify_sealed_file(
                output,
                password=PASSWORD,
                allow_plaintext_temp=True,
            )
            recovery_info = sealed_file.verify_sealed_file(
                output,
                recovery_key=recovery,
                allow_plaintext_temp=True,
            )
            self.assertEqual(password_info.original_name, source.name)
            self.assertEqual(password_info.original_sha256, recovery_info.original_sha256)

            password_out = root / "password-restored"
            restored = sealed_file.unseal_file(
                output,
                password_out,
                password=PASSWORD,
                allow_plaintext_temp=True,
                allow_plaintext_output=True,
            )
            self.assertEqual(Path(restored.output).read_bytes(), source.read_bytes())
            self.assertTrue(restored.sealed_source_retained)
            self.assertTrue(output.is_file())

            recovery_out = root / "recovery-restored"
            sealed_file.unseal_file(
                output,
                recovery_out,
                recovery_key=recovery,
                allow_plaintext_temp=True,
                allow_plaintext_output=True,
            )
            self.assertEqual(
                (recovery_out / source.name).read_bytes(),
                source.read_bytes(),
            )

    def test_empty_and_multichunk_incompressible_files_round_trip(self) -> None:
        for name, content in (
            ("empty.bin", b""),
            ("random.bin", os.urandom(5 * 1024 * 1024)),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, output, recovery, _ = self._seal(
                    root,
                    name=name,
                    content=content,
                )
                info = sealed_file.verify_sealed_file(
                    output,
                    recovery_key=recovery,
                    allow_plaintext_temp=True,
                )
                self.assertEqual(info.original_size, len(content))
                if content:
                    self.assertGreater(info.inner_size, 0)
                    self.assertGreater(
                        secure_engine.read_secure_info(output).chunk_count,
                        1,
                    )
                restored = root / "restored"
                sealed_file.unseal_file(
                    output,
                    restored,
                    recovery_key=recovery,
                    allow_plaintext_temp=True,
                    allow_plaintext_output=True,
                )
                self.assertEqual((restored / source.name).read_bytes(), content)

    def test_acknowledgements_fail_before_outputs_or_unlock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("secret", encoding="utf-8")
            output = root / "sealed" / "opaque.rtsf"
            recovery = root / "recovery" / "opaque.rtrk"

            with self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "explicit acknowledgement",
            ):
                sealed_file.seal_file(
                    source,
                    output,
                    password=PASSWORD,
                    recovery_key_output=recovery,
                )
            self.assertFalse(output.parent.exists())
            self.assertFalse(recovery.parent.exists())

            _, output, recovery, _ = self._seal(root)
            with mock.patch.object(
                secure_engine,
                "decrypt_file",
            ) as decrypt:
                with self.assertRaisesRegex(
                    sealed_file.SealedFileError,
                    "ordinary plaintext file",
                ):
                    sealed_file.unseal_file(
                        output,
                        root / "restored",
                        recovery_key=recovery,
                        allow_plaintext_temp=True,
                    )
            decrypt.assert_not_called()

    def test_wrong_key_tamper_and_truncation_publish_no_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, output, recovery, _ = self._seal(root)
            wrong_source = root / "other-plaintext" / "wrong.txt"
            wrong_source.parent.mkdir()
            wrong_source.write_text("other", encoding="utf-8")
            wrong_output = root / "wrong-sealed" / "wrong.rtsf"
            wrong_recovery = root / "wrong-recovery" / "wrong.rtrk"
            sealed_file.seal_file(
                wrong_source,
                wrong_output,
                password=PASSWORD,
                recovery_key_output=wrong_recovery,
                allow_plaintext_temp=True,
            )

            for label, candidate, credential in (
                ("wrong-key", output, wrong_recovery),
                ("tampered", root / "tampered.rtsf", recovery),
                ("truncated", root / "truncated.rtsf", recovery),
            ):
                if label == "tampered":
                    data = bytearray(output.read_bytes())
                    data[-1] ^= 1
                    candidate.write_bytes(data)
                elif label == "truncated":
                    candidate.write_bytes(output.read_bytes()[:-1])
                destination = root / f"{label}-restored"
                with self.subTest(label=label), self.assertRaises(
                    secure_engine.SecureArchiveError
                ):
                    sealed_file.unseal_file(
                        candidate,
                        destination,
                        recovery_key=credential,
                        allow_plaintext_temp=True,
                        allow_plaintext_output=True,
                    )
                self.assertFalse(destination.exists())

    def test_general_encrypted_archives_and_unsafe_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "plaintext" / "source.txt"
            source.parent.mkdir()
            source.write_text("secret", encoding="utf-8")

            for stored_name, expected_message in (
                ("nested/name.txt", "safe Windows"),
                ("CON.txt", "reserved by Windows"),
                ("file.txt:stream", "safe Windows"),
            ):
                with self.subTest(stored_name=stored_name):
                    inner = root / f"{len(list(root.iterdir()))}.gmw"
                    solid_engine.compress_file(
                        source,
                        inner,
                        profile=sealed_file.SEALED_PROFILE,
                        stored_name=stored_name,
                    )
                    outer = root / f"{inner.stem}.rtsf"
                    recovery = root / f"{inner.stem}.rtrk"
                    secure_engine.encrypt_file(
                        inner,
                        outer,
                        password=PASSWORD,
                        recovery_key_output=recovery,
                    )
                    with self.assertRaisesRegex(
                        sealed_file.SealedFileError,
                        expected_message,
                    ):
                        sealed_file.inspect_sealed_file(
                            outer,
                            recovery_key=recovery,
                            allow_plaintext_temp=True,
                        )

            normal_inner = root / "normal.gmw"
            solid_engine.compress_file(
                source,
                normal_inner,
                profile="balanced",
            )
            normal_outer = root / "normal.rtsf"
            normal_recovery = root / "normal.rtrk"
            secure_engine.encrypt_file(
                normal_inner,
                normal_outer,
                password=PASSWORD,
                recovery_key_output=normal_recovery,
            )
            with self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "not a valid Rat-Trap Sealed File",
            ):
                    sealed_file.inspect_sealed_file(
                        normal_outer,
                        recovery_key=normal_recovery,
                        allow_plaintext_temp=True,
                    )

    def test_profile_metadata_requires_exact_json_types(self) -> None:
        mutations = (
            ("compression_level", 6.0),
            ("file_count", True),
            ("directory_count", False),
            ("whole_file_dedup", 0),
            ("duplicate_file_count", 0.0),
            ("zstd_long_distance", 0),
            ("payload_bytes", None),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("authenticated exact-type test", encoding="utf-8")
            for field, invalid_value in mutations:
                with self.subTest(field=field):
                    inner = root / f"{field}.gmw"
                    solid_engine.compress_file(
                        source,
                        inner,
                        profile=sealed_file.SEALED_PROFILE,
                    )
                    archive = inner.read_bytes()
                    footer_size = 8 + len(solid_engine.FOOTER_MAGIC)
                    metadata_size = struct.unpack(
                        "<Q",
                        archive[
                            -footer_size : -len(solid_engine.FOOTER_MAGIC)
                        ],
                    )[0]
                    metadata_start = (
                        len(archive) - footer_size - metadata_size
                    )
                    metadata = json.loads(
                        archive[
                            metadata_start : metadata_start + metadata_size
                        ]
                    )
                    metadata[field] = (
                        float(metadata[field])
                        if field == "payload_bytes"
                        else invalid_value
                    )
                    encoded = json.dumps(
                        metadata,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                    inner.write_bytes(
                        archive[:metadata_start]
                        + encoded
                        + struct.pack("<Q", len(encoded))
                        + solid_engine.FOOTER_MAGIC
                    )
                    outer = root / f"{field}.rtsf"
                    recovery = root / f"{field}.rtrk"
                    secure_engine.encrypt_file(
                        inner,
                        outer,
                        password=PASSWORD,
                        recovery_key_output=recovery,
                    )

                    with self.assertRaisesRegex(
                        sealed_file.SealedFileError,
                        "not a valid Rat-Trap Sealed File",
                    ):
                        sealed_file.inspect_sealed_file(
                            outer,
                            recovery_key=recovery,
                            allow_plaintext_temp=True,
                        )

    def test_creation_refuses_collisions_hardlinks_and_recovery_beside_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "plaintext" / "source.txt"
            source.parent.mkdir()
            source.write_text("secret", encoding="utf-8")
            beside_output = root / "beside" / "opaque.rtsf"
            beside_recovery = root / "beside" / "opaque.rtrk"
            with self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "Store the recovery key separately",
            ):
                sealed_file.seal_file(
                    source,
                    beside_output,
                    password=PASSWORD,
                    recovery_key_output=beside_recovery,
                    allow_plaintext_temp=True,
                )

            alias = source.parent / "source-alias.txt"
            try:
                os.link(source, alias)
            except OSError as exc:
                self.skipTest(f"Filesystem cannot create hard links: {exc}")
            with self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "multiple hard-link",
            ):
                sealed_file.seal_file(
                    source,
                    root / "sealed" / "opaque.rtsf",
                    password=PASSWORD,
                    recovery_key_output=root / "recovery" / "opaque.rtrk",
                    allow_plaintext_temp=True,
                )

    def test_unseal_never_overwrites_even_with_replace_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output, recovery, _ = self._seal(root)
            restored = root / "restored"
            restored.mkdir()
            existing = restored / source.name
            existing.write_bytes(b"keep me")

            with self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "already exists",
            ):
                sealed_file.unseal_file(
                    output,
                    restored,
                    recovery_key=recovery,
                    allow_plaintext_temp=True,
                    allow_plaintext_output=True,
                )
            self.assertEqual(existing.read_bytes(), b"keep me")

            with self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "never overwrite",
            ):
                sealed_file.unseal_file(
                    output,
                    restored,
                    recovery_key=recovery,
                    allow_plaintext_temp=True,
                    allow_plaintext_output=True,
                    replace=True,
                )
            self.assertEqual(existing.read_bytes(), b"keep me")

    def test_password_and_recovery_rotation_reuse_the_existing_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, output, recovery, _ = self._seal(root)
            secure_engine.change_password(
                output,
                current_password=PASSWORD,
                new_password=NEW_PASSWORD,
            )
            with self.assertRaises(secure_engine.UnlockError):
                sealed_file.verify_sealed_file(
                    output,
                    password=PASSWORD,
                    allow_plaintext_temp=True,
                )
            sealed_file.verify_sealed_file(
                output,
                password=NEW_PASSWORD,
                allow_plaintext_temp=True,
            )

            replacement = root / "replacement-recovery" / "new.rtrk"
            secure_engine.rotate_recovery_key(
                output,
                replacement,
                password=NEW_PASSWORD,
            )
            with self.assertRaises(secure_engine.UnlockError):
                sealed_file.verify_sealed_file(
                    output,
                    recovery_key=recovery,
                    allow_plaintext_temp=True,
                )
            sealed_file.verify_sealed_file(
                output,
                recovery_key=replacement,
                allow_plaintext_temp=True,
            )

    def test_bulk_outputs_are_opaque_independent_and_sources_are_retained(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "nested").mkdir(parents=True)
            (source / "report.xlsx").write_bytes(b"sheet" * 100)
            (source / "nested" / "photo.jpg").write_bytes(os.urandom(2048))
            output = root / "sealed"
            recovery = root / "recovery"

            result = sealed_file.seal_folder(
                source,
                output,
                recovery,
                password=PASSWORD,
                allow_plaintext_temp=True,
            )
            self.assertTrue(result.completed)
            self.assertEqual(result.sealed_count, 2)
            self.assertEqual(result.failed_count, 0)
            self.assertTrue((source / "report.xlsx").is_file())
            self.assertTrue((source / "nested" / "photo.jpg").is_file())
            sealed_names = sorted(path.name for path in output.glob("*.rtsf"))
            self.assertEqual(len(sealed_names), 2)
            self.assertTrue(all(name.startswith("RT-") for name in sealed_names))
            self.assertNotIn("report", " ".join(sealed_names).lower())
            self.assertEqual(len(list(recovery.glob("*.rtrk"))), 2)

            for item in result.items:
                info = sealed_file.verify_sealed_file(
                    Path(item.output),
                    recovery_key=Path(item.recovery_key_path),
                    allow_plaintext_temp=True,
                )
                self.assertEqual(
                    info.original_name,
                    Path(item.source).name,
                )

    def test_invalid_password_fails_before_plaintext_work_or_directories(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "plaintext" / "source.txt"
            source.parent.mkdir()
            source.write_text("secret", encoding="utf-8")
            output = root / "sealed" / "opaque.rtsf"
            recovery = root / "recovery" / "opaque.rtrk"

            with (
                mock.patch.object(
                    solid_engine,
                    "compress_file",
                ) as compress,
                self.assertRaisesRegex(
                    sealed_file.SealedFileError,
                    "at least",
                ),
            ):
                sealed_file.seal_file(
                    source,
                    output,
                    password="too short",
                    recovery_key_output=recovery,
                    allow_plaintext_temp=True,
                )

            compress.assert_not_called()
            self.assertFalse(output.parent.exists())
            self.assertFalse(recovery.parent.exists())

    def test_recovery_and_bulk_trees_must_be_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plaintext = root / "plaintext"
            plaintext.mkdir()
            source = plaintext / "source.txt"
            source.write_text("secret", encoding="utf-8")

            with self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "outside the plaintext",
            ):
                sealed_file.seal_file(
                    source,
                    root / "sealed" / "opaque.rtsf",
                    password=PASSWORD,
                    recovery_key_output=plaintext / "opaque.rtrk",
                    allow_plaintext_temp=True,
                )

            with self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "must not contain",
            ):
                sealed_file.seal_file(
                    source,
                    root / "store" / "opaque.rtsf",
                    password=PASSWORD,
                    recovery_key_output=(
                        root / "store" / "keys" / "opaque.rtrk"
                    ),
                    allow_plaintext_temp=True,
                )

            folder_source = root / "bulk-source"
            folder_source.mkdir()
            (folder_source / "one.txt").write_text(
                "one",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "do not contain",
            ):
                sealed_file.seal_folder(
                    folder_source,
                    root / "bulk-output",
                    root / "bulk-output" / "keys",
                    password=PASSWORD,
                    allow_plaintext_temp=True,
                )

    def test_profile_is_verified_before_publication_and_orphan_is_reported(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "plaintext" / "source.txt"
            source.parent.mkdir()
            source.write_text("secret", encoding="utf-8")
            output = root / "sealed" / "opaque.rtsf"
            recovery = root / "recovery" / "opaque.rtrk"

            with (
                mock.patch.object(
                    sealed_file,
                    "inspect_sealed_file",
                    side_effect=sealed_file.SealedFileError(
                        "forced staged-profile rejection"
                    ),
                ),
                self.assertRaisesRegex(
                    sealed_file.SealedFileError,
                    "orphan recovery key",
                ),
            ):
                sealed_file.seal_file(
                    source,
                    output,
                    password=PASSWORD,
                    recovery_key_output=recovery,
                    allow_plaintext_temp=True,
                )

            self.assertFalse(output.exists())
            self.assertTrue(recovery.is_file())
            secure_engine.read_recovery_key_file(recovery)

    def test_source_hardlink_change_is_rechecked_before_publication(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "plaintext" / "source.txt"
            source.parent.mkdir()
            source.write_text("secret", encoding="utf-8")
            alias = source.parent / "new-hardlink.txt"
            output = root / "sealed" / "opaque.rtsf"
            recovery = root / "recovery" / "opaque.rtrk"

            def mutate_before_publish(_inner, _output, **kwargs):
                try:
                    os.link(source, alias)
                except OSError as exc:
                    self.skipTest(
                        f"Filesystem cannot create hard links: {exc}"
                    )
                kwargs["pre_publish_validator"](
                    root / "staged.rtsf",
                    recovery,
                )
                raise AssertionError("validator should reject the hard link")

            with (
                mock.patch.object(
                    secure_engine,
                    "encrypt_file",
                    side_effect=mutate_before_publish,
                ),
                self.assertRaisesRegex(
                    sealed_file.SealedFileError,
                    "multiple hard-link",
                ),
            ):
                sealed_file.seal_file(
                    source,
                    output,
                    password=PASSWORD,
                    recovery_key_output=recovery,
                    allow_plaintext_temp=True,
                )

            self.assertFalse(output.exists())
            self.assertFalse(recovery.exists())

    def test_locked_generic_envelope_does_not_claim_sealed_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inner = root / "ordinary.gmw"
            inner.write_bytes(b"ordinary archive bytes")
            encrypted = root / "candidate.rtsf"
            recovery = root / "candidate.rtrk"
            secure_engine.encrypt_file(
                inner,
                encrypted,
                password=PASSWORD,
                recovery_key_output=recovery,
            )

            info = sealed_file.read_locked_info(encrypted)

            self.assertIsNone(info.profile_format)
            self.assertIsNone(info.profile_schema_version)
            self.assertFalse(info.profile_verified)

    def test_resource_limits_fail_before_decryption_or_compression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output, recovery, _ = self._seal(root)

            with (
                mock.patch.object(
                    sealed_file,
                    "DEFAULT_MAX_INNER_BYTES",
                    1,
                ),
                mock.patch.object(
                    secure_engine,
                    "decrypt_file",
                ) as decrypt,
                self.assertRaisesRegex(
                    sealed_file.SealedFileError,
                    "configured limit",
                ),
            ):
                sealed_file.inspect_sealed_file(
                    output,
                    recovery_key=recovery,
                    allow_plaintext_temp=True,
                )
            decrypt.assert_not_called()

            new_output = root / "other-sealed" / "opaque.rtsf"
            new_recovery = root / "other-recovery" / "opaque.rtrk"
            with (
                mock.patch.object(
                    sealed_file,
                    "DEFAULT_MAX_ORIGINAL_BYTES",
                    1,
                ),
                mock.patch.object(
                    solid_engine,
                    "compress_file",
                ) as compress,
                self.assertRaisesRegex(
                    sealed_file.SealedFileError,
                    "supports original files",
                ),
            ):
                sealed_file.seal_file(
                    source,
                    new_output,
                    password=PASSWORD,
                    recovery_key_output=new_recovery,
                    allow_plaintext_temp=True,
                )
            compress.assert_not_called()

    def test_bulk_final_reconciliation_reports_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "one.txt").write_text("one", encoding="utf-8")
            output = root / "sealed"
            recovery = root / "recovery"

            def fake_seal(
                _source,
                sealed_path,
                *,
                recovery_key_output,
                **_kwargs,
            ):
                Path(sealed_path).write_bytes(b"sealed")
                Path(recovery_key_output).write_bytes(b"recovery")
                (source / "new.txt").write_text("new", encoding="utf-8")

            with mock.patch.object(
                sealed_file,
                "seal_file",
                side_effect=fake_seal,
            ):
                result = sealed_file.seal_folder(
                    source,
                    output,
                    recovery,
                    password=PASSWORD,
                    allow_plaintext_temp=True,
                )

            self.assertFalse(result.completed)
            self.assertEqual(result.sealed_count, 1)
            self.assertEqual(result.unprocessed_count, 1)
            self.assertEqual(result.failed_count, 0)
            self.assertIn(
                "new.txt",
                [item.relative_source for item in result.items],
            )

    def test_bulk_final_reconciliation_reports_removed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            original = source / "one.txt"
            original.write_text("one", encoding="utf-8")
            output = root / "sealed"
            recovery = root / "recovery"

            def fake_seal(
                _source,
                sealed_path,
                *,
                recovery_key_output,
                **_kwargs,
            ):
                Path(sealed_path).write_bytes(b"sealed")
                Path(recovery_key_output).write_bytes(b"recovery")
                original.unlink()

            with mock.patch.object(
                sealed_file,
                "seal_file",
                side_effect=fake_seal,
            ):
                result = sealed_file.seal_folder(
                    source,
                    output,
                    recovery,
                    password=PASSWORD,
                    allow_plaintext_temp=True,
                )

            self.assertFalse(result.completed)
            self.assertEqual(result.sealed_count, 1)
            self.assertEqual(result.unprocessed_count, 1)
            self.assertEqual(result.failed_count, 0)
            removed = [
                item
                for item in result.items
                if item.status == "unprocessed"
            ]
            self.assertEqual(len(removed), 1)
            self.assertEqual(removed[0].relative_source, "one.txt")
            self.assertIn("removed", removed[0].error or "")

    def test_bulk_traversal_errors_fail_closed_before_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "one.txt").write_text("one", encoding="utf-8")
            output = root / "sealed"
            recovery = root / "recovery"

            def inaccessible_walk(
                _root,
                *,
                topdown,
                onerror,
                followlinks,
            ):
                self.assertTrue(topdown)
                self.assertFalse(followlinks)
                onerror(PermissionError("injected access denied"))
                return iter(())

            with (
                mock.patch.object(
                    sealed_file.os,
                    "walk",
                    side_effect=inaccessible_walk,
                ),
                self.assertRaisesRegex(
                    sealed_file.SealedFileError,
                    "complete bulk source tree",
                ),
            ):
                sealed_file.seal_folder(
                    source,
                    output,
                    recovery,
                    password=PASSWORD,
                    allow_plaintext_temp=True,
                )

            self.assertFalse(output.exists())
            self.assertFalse(recovery.exists())

    def test_reparse_check_does_not_ignore_a_dangling_path(self) -> None:
        missing = Path("missing-dangling-link.rtsf")
        with (
            mock.patch.object(
                sealed_file.repository_engine,
                "_is_link_or_junction",
                side_effect=lambda path: path.name == missing.name,
            ),
            self.assertRaisesRegex(
                sealed_file.SealedFileError,
                "reparse point",
            ),
        ):
            sealed_file._reject_reparse(
                missing,
                label="Test output",
            )


if __name__ == "__main__":
    unittest.main()
