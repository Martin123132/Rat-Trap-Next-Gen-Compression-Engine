import base64
import hashlib
import json
import os
import shutil
import struct
import tempfile
import threading
import unittest
import unicodedata
from pathlib import Path
from unittest import mock

from rat_trap import secure_engine


PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "new correct horse battery staple"
PLAINTEXT_MARKER = b"RAT-TRAP-PRIVATE-MARKER-DO-NOT-LEAK"
MINIMUM_CHUNK_SIZE = 64 * 1024


def _fast_test_argon2(password: bytes, salt: bytes, file_id: str) -> bytes:
    """Cheap deterministic stand-in used only for non-KDF edge cases."""

    return hashlib.sha256(
        b"rat-trap-test-kdf\x00"
        + password
        + salt
        + bytes.fromhex(file_id)
    ).digest()


def _header_bounds(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    magic_size = len(secure_engine.SECURE_MAGIC)
    header_size = struct.unpack(
        "<I", raw[magic_size : magic_size + 4]
    )[0]
    start = magic_size + 4
    return start, start + header_size


def _payload_tail(path: Path) -> bytes:
    _, data_offset = _header_bounds(path)
    return path.read_bytes()[data_offset:]


def _tamper_authenticated_header(path: Path) -> None:
    raw = bytearray(path.read_bytes())
    start, end = _header_bounds(path)
    header = json.loads(bytes(raw[start:end]).decode("utf-8"))
    tag = bytearray(
        base64.b64decode(header["header_auth"]["ciphertext"], validate=True)
    )
    tag[0] ^= 0x01
    header["header_auth"]["ciphertext"] = base64.b64encode(tag).decode("ascii")
    encoded = json.dumps(
        header,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) != end - start:
        raise AssertionError("Header mutation unexpectedly changed its size")
    raw[start:end] = encoded
    path.write_bytes(raw)


def _tamper_first_chunk(path: Path) -> None:
    raw = bytearray(path.read_bytes())
    _, data_offset = _header_bounds(path)
    first_ciphertext_byte = data_offset + 12
    raw[first_ciphertext_byte] ^= 0x01
    path.write_bytes(raw)


class SecureEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._fixture_directory = tempfile.TemporaryDirectory()
        fixture_root = Path(cls._fixture_directory.name)
        cls.fixture_plaintext = (
            PLAINTEXT_MARKER
            + b"\x00"
            + bytes(range(256)) * 700
            + b"fixture-end"
        )
        source = fixture_root / "fixture-inner.gmw"
        source.write_bytes(cls.fixture_plaintext)
        cls.fixture_archive = fixture_root / "fixture-secure.gmw"
        cls.fixture_recovery = fixture_root / "fixture-recovery.rtrk"

        # This one shared fixture exercises the production Argon2id profile.
        secure_engine.encrypt_file(
            source,
            cls.fixture_archive,
            password=PASSWORD,
            recovery_key_output=cls.fixture_recovery,
            chunk_size=MINIMUM_CHUNK_SIZE,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._fixture_directory.cleanup()

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.archive = self.root / "secure.gmw"
        self.recovery = self.root / "recovery.rtrk"
        shutil.copy2(self.fixture_archive, self.archive)
        shutil.copy2(self.fixture_recovery, self.recovery)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _assert_decrypt_failure_leaves_no_output(
        self,
        archive: Path,
        *,
        password: str | None = None,
        recovery_key: str | bytes | Path | None = None,
    ) -> None:
        output = self.root / f"{archive.stem}-failed-output.gmw"
        with self.assertRaises(secure_engine.SecureArchiveError):
            secure_engine.decrypt_file(
                archive,
                output,
                password=password,
                recovery_key=recovery_key,
            )
        self.assertFalse(output.exists())
        self.assertEqual(
            list(output.parent.glob(f".{output.name}.decrypting-*.tmp")),
            [],
        )

    def test_password_and_recovery_round_trip_multichunk_archive(self) -> None:
        locked = secure_engine.read_secure_info(self.archive)
        self.assertEqual(locked.chunk_size, MINIMUM_CHUNK_SIZE)
        self.assertGreaterEqual(locked.chunk_count, 3)

        password_output = self.root / "password-output.gmw"
        password_result = secure_engine.decrypt_file(
            self.archive,
            password_output,
            password=PASSWORD,
        )
        recovery_output = self.root / "recovery-output.gmw"
        recovery_result = secure_engine.decrypt_file(
            self.archive,
            recovery_output,
            recovery_key=self.recovery,
        )

        self.assertEqual(password_output.read_bytes(), self.fixture_plaintext)
        self.assertEqual(recovery_output.read_bytes(), self.fixture_plaintext)
        self.assertTrue(password_result.secure_file.verified)
        self.assertTrue(recovery_result.secure_file.verified)
        self.assertEqual(
            password_result.plaintext_sha256,
            hashlib.sha256(self.fixture_plaintext).hexdigest(),
        )

    def test_empty_file_round_trip_with_both_credentials(self) -> None:
        source = self.root / "empty.gmw"
        source.write_bytes(b"")
        archive = self.root / "empty-secure.gmw"
        recovery = self.root / "empty-recovery.rtrk"

        with mock.patch.object(
            secure_engine, "_argon2_key", side_effect=_fast_test_argon2
        ):
            created = secure_engine.encrypt_file(
                source,
                archive,
                password=PASSWORD,
                recovery_key_output=recovery,
                chunk_size=MINIMUM_CHUNK_SIZE,
            )
            password_output = self.root / "empty-password.gmw"
            secure_engine.decrypt_file(
                archive, password_output, password=PASSWORD
            )
            recovery_output = self.root / "empty-recovery.gmw"
            secure_engine.decrypt_file(
                archive, recovery_output, recovery_key=recovery
            )

        self.assertEqual(created.secure_file.plaintext_size, 0)
        self.assertEqual(created.secure_file.chunk_count, 0)
        self.assertTrue(created.secure_file.verified)
        self.assertEqual(password_output.read_bytes(), b"")
        self.assertEqual(recovery_output.read_bytes(), b"")

    def test_ciphertext_does_not_contain_known_plaintext_marker(self) -> None:
        self.assertIn(PLAINTEXT_MARKER, self.fixture_plaintext)
        self.assertNotIn(PLAINTEXT_MARKER, self.archive.read_bytes())
        self.assertTrue(secure_engine.is_encrypted_archive(self.archive))
        self.assertFalse(secure_engine.is_encrypted_archive(self.recovery))
        self.assertFalse(
            secure_engine.is_encrypted_archive(self.root / "missing.gmw")
        )

    def test_locked_and_verified_information_are_distinct(self) -> None:
        locked = secure_engine.read_secure_info(self.archive)
        locked_values = locked.as_dict()
        self.assertFalse(locked.verified)
        self.assertEqual(locked.format, secure_engine.SECURE_FORMAT)
        self.assertEqual(locked.schema_version, 1)
        self.assertEqual(locked.cipher, "AES-256-GCM-SIV")
        self.assertEqual(locked.password_slot_count, 1)
        self.assertEqual(locked.recovery_slot_count, 1)
        self.assertEqual(locked.plaintext_size, len(self.fixture_plaintext))
        self.assertNotIn("plaintext_sha256", locked_values)

        verified = secure_engine.verify_encrypted_file(
            self.archive, recovery_key=self.recovery
        )
        self.assertTrue(verified.verified)
        self.assertEqual(verified.file_id, locked.file_id)

        with self.assertRaises(secure_engine.UnlockRequiredError):
            secure_engine.verify_encrypted_file(self.archive)
        with self.assertRaises(secure_engine.UnlockRequiredError):
            secure_engine.verify_encrypted_file(
                self.archive,
                password=PASSWORD,
                recovery_key=self.recovery,
            )

    def test_wrong_password_and_recovery_key_publish_no_plaintext(self) -> None:
        self._assert_decrypt_failure_leaves_no_output(
            self.archive, password="definitely wrong"
        )
        self._assert_decrypt_failure_leaves_no_output(
            self.archive, recovery_key=os.urandom(32)
        )

        wrong_file = self.root / "different-archive.rtrk"
        secure_engine.write_recovery_key_file(
            wrong_file,
            file_id="0" * 32,
            recovery_key=bytes(range(32)),
            created_at_ns=1,
        )
        self._assert_decrypt_failure_leaves_no_output(
            self.archive, recovery_key=wrong_file
        )

    def test_header_chunk_truncation_and_trailing_tampering_are_rejected(self) -> None:
        mutations = {
            "header": _tamper_authenticated_header,
            "chunk": _tamper_first_chunk,
            "truncated": lambda path: path.write_bytes(
                path.read_bytes()[:-1]
            ),
            "trailing": lambda path: path.write_bytes(
                path.read_bytes() + b"unexpected trailing bytes"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                damaged = self.root / f"{label}.gmw"
                shutil.copy2(self.archive, damaged)
                mutate(damaged)
                self._assert_decrypt_failure_leaves_no_output(
                    damaged, recovery_key=self.recovery
                )

    def test_hostile_kdf_parameters_fail_before_password_work(self) -> None:
        raw = self.archive.read_bytes()
        start, end = _header_bounds(self.archive)
        header = json.loads(raw[start:end].decode("utf-8"))
        password_slot = next(
            slot for slot in header["key_slots"] if slot["type"] == "password"
        )
        password_slot["kdf"]["memory_kib"] = 2**31
        encoded = json.dumps(
            header,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        hostile = self.root / "hostile-kdf.gmw"
        hostile.write_bytes(
            secure_engine.SECURE_MAGIC
            + struct.pack("<I", len(encoded))
            + encoded
            + raw[end:]
        )

        with mock.patch.object(
            secure_engine,
            "_argon2_key",
            side_effect=AssertionError("unsafe KDF must not run"),
        ):
            with self.assertRaisesRegex(
                secure_engine.SecureArchiveError, "KDF parameters"
            ):
                secure_engine.verify_encrypted_file(
                    hostile, password=PASSWORD
                )

    def test_hostile_json_numbers_and_surrogates_are_rejected_cleanly(
        self,
    ) -> None:
        raw = self.archive.read_bytes()
        start, end = _header_bounds(self.archive)
        original = json.loads(raw[start:end].decode("utf-8"))
        mutations = {
            "nan": ("created_at_ns", float("nan")),
            "surrogate": ("writer_version", "\ud800"),
        }
        for label, (field, value) in mutations.items():
            with self.subTest(label=label):
                header = dict(original)
                header[field] = value
                encoded = json.dumps(
                    header,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=True,
                ).encode("ascii")
                hostile = self.root / f"hostile-json-{label}.gmw"
                hostile.write_bytes(
                    secure_engine.SECURE_MAGIC
                    + struct.pack("<I", len(encoded))
                    + encoded
                    + raw[end:]
                )
                with self.assertRaisesRegex(
                    secure_engine.SecureArchiveError,
                    "security header is invalid",
                ):
                    secure_engine.read_secure_info(hostile)

    def test_authenticated_hostile_sealed_json_is_rejected_cleanly(
        self,
    ) -> None:
        unlocked = secure_engine._unlock_header(
            self.archive,
            recovery_key=self.recovery,
        )
        original = self.archive.read_bytes()
        _, data_offset = _header_bounds(self.archive)
        prefix = (
            b'{"format":"RAT-TRAP-SEALED-METADATA-1",'
            b'"plaintext_sha256":'
        )
        hostile_values = {
            "nan": b" " * 63 + b"NaN",
            "surrogate": b'"\\ud800' + b"0" * 58 + b'"',
        }
        for label, value in hostile_values.items():
            with self.subTest(label=label):
                metadata_bytes = prefix + value + b"}"
                self.assertEqual(len(metadata_bytes), 125)
                header = json.loads(json.dumps(unlocked.header))
                nonce = os.urandom(12)
                header["sealed_metadata"] = {
                    "cipher": "AES-256-GCM-SIV",
                    "nonce": base64.b64encode(nonce).decode("ascii"),
                    "ciphertext": base64.b64encode(
                        secure_engine.AESGCMSIV(
                            unlocked.data_key
                        ).encrypt(
                            nonce,
                            metadata_bytes,
                            secure_engine._METADATA_AAD_PREFIX
                            + unlocked.data_context,
                        )
                    ).decode("ascii"),
                }
                header["header_auth"] = secure_engine._new_header_auth(
                    secure_engine._header_without_auth(header),
                    unlocked.data_key,
                )
                encoded = secure_engine._canonical_json(header)
                hostile = self.root / f"hostile-sealed-{label}.gmw"
                hostile.write_bytes(
                    secure_engine.SECURE_MAGIC
                    + struct.pack("<I", len(encoded))
                    + encoded
                    + original[data_offset:]
                )

                with self.assertRaisesRegex(
                    secure_engine.SecureArchiveError,
                    "sealed metadata is invalid",
                ):
                    secure_engine.verify_encrypted_file(
                        hostile,
                        recovery_key=self.recovery,
                    )

    def test_boolean_schema_versions_are_not_accepted_as_integers(
        self,
    ) -> None:
        raw = self.archive.read_bytes()
        start, end = _header_bounds(self.archive)
        header = json.loads(raw[start:end].decode("utf-8"))
        header["schema_version"] = True
        encoded_header = json.dumps(
            header,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        hostile_archive = self.root / "boolean-schema.gmw"
        hostile_archive.write_bytes(
            secure_engine.SECURE_MAGIC
            + struct.pack("<I", len(encoded_header))
            + encoded_header
            + raw[end:]
        )
        with self.assertRaisesRegex(
            secure_engine.SecureArchiveError,
            "header values are invalid",
        ):
            secure_engine.read_secure_info(hostile_archive)

        recovery_payload = json.loads(self.recovery.read_bytes())
        recovery_payload["schema_version"] = True
        hostile_recovery = self.root / "boolean-schema.rtrk"
        hostile_recovery.write_bytes(
            json.dumps(
                recovery_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        with self.assertRaises(secure_engine.RecoveryKeyError):
            secure_engine.read_recovery_key_file(hostile_recovery)

    def test_nested_kdf_numeric_fields_require_exact_integers(self) -> None:
        raw = self.archive.read_bytes()
        start, end = _header_bounds(self.archive)
        original = json.loads(raw[start:end].decode("utf-8"))
        mutations = (
            ("password", "length"),
            ("password", "memory_kib"),
            ("password", "iterations"),
            ("password", "lanes"),
            ("recovery", "length"),
        )
        for slot_type, field in mutations:
            with self.subTest(slot_type=slot_type, field=field):
                header = json.loads(json.dumps(original))
                slot = next(
                    item
                    for item in header["key_slots"]
                    if item["type"] == slot_type
                )
                slot["kdf"][field] = float(slot["kdf"][field])
                encoded = json.dumps(
                    header,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
                hostile = self.root / f"float-{slot_type}-{field}.gmw"
                hostile.write_bytes(
                    secure_engine.SECURE_MAGIC
                    + struct.pack("<I", len(encoded))
                    + encoded
                    + raw[end:]
                )
                with self.assertRaisesRegex(
                    secure_engine.SecureArchiveError,
                    "KDF parameters are unsupported",
                ):
                    secure_engine.read_secure_info(hostile)

    def test_malformed_password_unicode_is_rejected_without_echo(self) -> None:
        archive_before = self.archive.read_bytes()
        marker = "do-not-echo-this-password"
        with self.assertRaises(secure_engine.SecureArchiveError) as raised:
            secure_engine.change_password(
                self.archive,
                new_password="\ud800" + marker,
                recovery_key=self.recovery,
            )

        self.assertNotIn(marker, str(raised.exception))
        self.assertEqual(self.archive.read_bytes(), archive_before)

    def test_recovery_code_round_trip_and_transcription_checks(self) -> None:
        key = bytes(range(32))
        encoded = secure_engine.encode_recovery_key(key)
        decorated = encoded.lower().replace("-", " - \n")
        self.assertEqual(secure_engine.decode_recovery_key(decorated), key)

        compact = encoded.replace("-", "")
        mutation_index = len("RTRK1") + 7
        replacement = "A" if compact[mutation_index] != "A" else "B"
        corrupted = (
            compact[:mutation_index]
            + replacement
            + compact[mutation_index + 1 :]
        )
        with self.assertRaises(secure_engine.RecoveryKeyError):
            secure_engine.decode_recovery_key(corrupted)
        with self.assertRaises(secure_engine.RecoveryKeyError):
            secure_engine.decode_recovery_key("NOT-A-RAT-TRAP-KEY")
        with self.assertRaises(secure_engine.RecoveryKeyError):
            secure_engine.encode_recovery_key(b"too short")

    def test_recovery_key_file_is_canonical_validated_and_never_overwritten(
        self,
    ) -> None:
        file_id, key = secure_engine.read_recovery_key_file(self.recovery)
        info = secure_engine.read_secure_info(self.archive)
        self.assertEqual(file_id, info.file_id)
        self.assertEqual(len(key), 32)
        raw = self.recovery.read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(
            json.dumps(
                json.loads(raw),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
            raw[:-1],
        )

        original = raw
        with self.assertRaises(secure_engine.RecoveryKeyError):
            secure_engine.write_recovery_key_file(
                self.recovery,
                file_id=file_id,
                recovery_key=os.urandom(32),
            )
        self.assertEqual(self.recovery.read_bytes(), original)

        noncanonical = self.root / "noncanonical.rtrk"
        noncanonical.write_text(
            json.dumps(json.loads(raw), indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(secure_engine.RecoveryKeyError):
            secure_engine.read_recovery_key_file(noncanonical)

        unexpected_field = self.root / "extra-field.rtrk"
        payload = json.loads(raw)
        payload["unexpected"] = True
        unexpected_field.write_text(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(secure_engine.RecoveryKeyError):
            secure_engine.read_recovery_key_file(unexpected_field)

        noncanonical_code = self.root / "noncanonical-code.rtrk"
        payload = json.loads(raw)
        payload["recovery_key"] = payload["recovery_key"].lower()
        noncanonical_code.write_bytes(
            secure_engine._canonical_json(payload) + b"\n"
        )
        with self.assertRaisesRegex(
            secure_engine.RecoveryKeyError,
            "canonical",
        ):
            secure_engine.read_recovery_key_file(noncanonical_code)

        parsed = json.loads(raw)
        hostile_values = {
            "nan": ("created_at_ns", float("nan")),
            "surrogate": ("file_id", "\ud800"),
        }
        for label, (field, value) in hostile_values.items():
            with self.subTest(label=label):
                hostile_payload = dict(parsed)
                hostile_payload[field] = value
                hostile = self.root / f"hostile-{label}.rtrk"
                hostile.write_bytes(
                    (
                        json.dumps(
                            hostile_payload,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=True,
                            allow_nan=True,
                        )
                        + "\n"
                    ).encode("ascii")
                )
                with self.assertRaises(secure_engine.RecoveryKeyError):
                    secure_engine.read_recovery_key_file(hostile)

    def test_passwords_are_normalized_to_unicode_nfc(self) -> None:
        decomposed = "Cafe\u0301 passphrase with enough length"
        composed = unicodedata.normalize("NFC", decomposed)
        self.assertNotEqual(decomposed, composed)
        source = self.root / "unicode.gmw"
        source.write_bytes(b"unicode password test")
        archive = self.root / "unicode-secure.gmw"
        recovery = self.root / "unicode-recovery.rtrk"

        with mock.patch.object(
            secure_engine, "_argon2_key", side_effect=_fast_test_argon2
        ):
            secure_engine.encrypt_file(
                source,
                archive,
                password=decomposed,
                recovery_key_output=recovery,
            )
            verified = secure_engine.verify_encrypted_file(
                archive, password=composed
            )
            output = self.root / "unicode-output.gmw"
            secure_engine.decrypt_file(
                archive, output, password=composed
            )

        self.assertTrue(verified.verified)
        self.assertEqual(output.read_bytes(), source.read_bytes())

    def test_password_rotation_rewraps_only_header(self) -> None:
        payload_before = _payload_tail(self.archive)
        rotated = secure_engine.change_password(
            self.archive,
            new_password=NEW_PASSWORD,
            recovery_key=self.recovery,
        )
        self.assertTrue(rotated.verified)
        self.assertEqual(_payload_tail(self.archive), payload_before)

        with self.assertRaises(secure_engine.UnlockError):
            secure_engine.verify_encrypted_file(
                self.archive, password=PASSWORD
            )
        self.assertTrue(
            secure_engine.verify_encrypted_file(
                self.archive, password=NEW_PASSWORD
            ).verified
        )
        self.assertTrue(
            secure_engine.verify_encrypted_file(
                self.archive, recovery_key=self.recovery
            ).verified
        )

    def test_recovery_rotation_revokes_old_key_and_keeps_password(self) -> None:
        payload_before = _payload_tail(self.archive)
        new_recovery = self.root / "rotated-recovery.rtrk"
        result = secure_engine.rotate_recovery_key(
            self.archive,
            new_recovery,
            current_recovery_key=self.recovery,
        )
        self.assertTrue(result.secure_file.verified)
        self.assertEqual(result.recovery_key_path, str(new_recovery.resolve()))
        self.assertEqual(_payload_tail(self.archive), payload_before)

        with self.assertRaises(secure_engine.UnlockError):
            secure_engine.verify_encrypted_file(
                self.archive, recovery_key=self.recovery
            )
        self.assertTrue(
            secure_engine.verify_encrypted_file(
                self.archive, recovery_key=new_recovery
            ).verified
        )
        self.assertTrue(
            secure_engine.verify_encrypted_file(
                self.archive, password=PASSWORD
            ).verified
        )

    def test_overlapping_credential_mutations_cannot_both_succeed(
        self,
    ) -> None:
        entered_password_slot = threading.Event()
        release_password_slot = threading.Event()
        password_result: list[secure_engine.SecureFileInfo] = []
        password_errors: list[BaseException] = []
        original_new_password_slot = secure_engine._new_password_slot

        def paused_password_slot(*args: object, **kwargs: object):
            entered_password_slot.set()
            if not release_password_slot.wait(timeout=10):
                raise AssertionError("Timed out releasing password mutation")
            return original_new_password_slot(*args, **kwargs)

        def update_password() -> None:
            try:
                password_result.append(
                    secure_engine.change_password(
                        self.archive,
                        new_password=NEW_PASSWORD,
                        recovery_key=self.recovery,
                    )
                )
            except BaseException as exc:
                password_errors.append(exc)

        rotated_recovery = self.root / "concurrent-recovery.rtrk"
        with (
            mock.patch.object(
                secure_engine,
                "_argon2_key",
                side_effect=_fast_test_argon2,
            ),
            mock.patch.object(
                secure_engine,
                "_new_password_slot",
                side_effect=paused_password_slot,
            ),
        ):
            thread = threading.Thread(
                target=update_password,
                name="rat-trap-password-mutation-test",
            )
            thread.start()
            self.assertTrue(
                entered_password_slot.wait(timeout=10),
                "Password mutation did not reach its controlled pause",
            )
            try:
                with self.assertRaisesRegex(
                    secure_engine.SecureArchiveError,
                    "credential update",
                ):
                    secure_engine.rotate_recovery_key(
                        self.archive,
                        rotated_recovery,
                        current_recovery_key=self.recovery,
                    )
            finally:
                release_password_slot.set()
                thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(password_errors, [])
            self.assertEqual(len(password_result), 1)
            self.assertTrue(
                secure_engine.verify_encrypted_file(
                    self.archive, password=NEW_PASSWORD
                ).verified
            )

        self.assertFalse(rotated_recovery.exists())
        self.assertTrue(
            secure_engine.verify_encrypted_file(
                self.archive, recovery_key=self.recovery
            ).verified
        )

    def test_stale_header_rewrite_is_rejected_before_commit(self) -> None:
        first = secure_engine._unlock_header(
            self.archive, recovery_key=self.recovery
        )
        stale = secure_engine._unlock_header(
            self.archive, recovery_key=self.recovery
        )

        def replacement_header(
            unlocked: secure_engine._UnlockedHeader,
            password: str,
        ) -> dict[str, object]:
            header = dict(unlocked.header)
            slots = [
                dict(slot)
                for slot in list(header["key_slots"])  # type: ignore[arg-type]
            ]
            replacement = secure_engine._new_password_slot(
                unlocked.data_key,
                password,
                file_id=str(header["file_id"]),
                data_context=unlocked.data_context,
            )
            header["key_slots"] = [
                replacement if slot["type"] == "password" else slot
                for slot in slots
            ]
            return header

        first_password = "first replacement password"
        stale_password = "stale replacement password"
        with mock.patch.object(
            secure_engine, "_argon2_key", side_effect=_fast_test_argon2
        ):
            first_header = replacement_header(first, first_password)
            stale_header = replacement_header(stale, stale_password)
            secure_engine._rewrite_header(
                self.archive,
                first,
                first_header,
                verify_password=first_password,
            )
            committed = self.archive.read_bytes()
            with self.assertRaisesRegex(
                secure_engine.SecureArchiveError,
                "no stale update was committed",
            ):
                secure_engine._rewrite_header(
                    self.archive,
                    stale,
                    stale_header,
                    verify_password=stale_password,
                )
            self.assertEqual(self.archive.read_bytes(), committed)
            self.assertTrue(
                secure_engine.verify_encrypted_file(
                    self.archive, password=first_password
                ).verified
            )
            with self.assertRaises(secure_engine.UnlockError):
                secure_engine.verify_encrypted_file(
                    self.archive, password=stale_password
                )

    def test_failed_recovery_rotation_retracts_new_key_file(self) -> None:
        archive_before = self.archive.read_bytes()
        new_recovery = self.root / "uncommitted-recovery.rtrk"
        with mock.patch.object(
            secure_engine,
            "_rewrite_header",
            side_effect=OSError("simulated archive commit failure"),
        ):
            with self.assertRaisesRegex(OSError, "simulated archive"):
                secure_engine.rotate_recovery_key(
                    self.archive,
                    new_recovery,
                    current_recovery_key=self.recovery,
                )

        self.assertFalse(new_recovery.exists())
        self.assertEqual(self.archive.read_bytes(), archive_before)
        self.assertTrue(
            secure_engine.verify_encrypted_file(
                self.archive, recovery_key=self.recovery
            ).verified
        )

    def test_creation_decryption_and_rotation_collisions_are_safe(self) -> None:
        source = self.root / "collision-source.gmw"
        source.write_bytes(b"source must survive")
        existing_output = self.root / "existing-secure.gmw"
        existing_output.write_bytes(b"existing encrypted destination")
        unused_recovery = self.root / "unused.rtrk"

        with self.assertRaises(secure_engine.SecureArchiveError):
            secure_engine.encrypt_file(
                source,
                existing_output,
                password=PASSWORD,
                recovery_key_output=unused_recovery,
            )
        self.assertEqual(
            existing_output.read_bytes(), b"existing encrypted destination"
        )
        self.assertFalse(unused_recovery.exists())

        existing_recovery = self.root / "existing.rtrk"
        existing_recovery.write_bytes(b"existing recovery destination")
        unused_output = self.root / "unused-secure.gmw"
        with self.assertRaises(secure_engine.RecoveryKeyError):
            secure_engine.encrypt_file(
                source,
                unused_output,
                password=PASSWORD,
                recovery_key_output=existing_recovery,
            )
        self.assertEqual(
            existing_recovery.read_bytes(), b"existing recovery destination"
        )
        self.assertFalse(unused_output.exists())

        plaintext_destination = self.root / "existing-plaintext.gmw"
        plaintext_destination.write_bytes(b"do not replace")
        with self.assertRaises(secure_engine.SecureArchiveError):
            secure_engine.decrypt_file(
                self.archive,
                plaintext_destination,
                recovery_key=self.recovery,
            )
        self.assertEqual(
            plaintext_destination.read_bytes(), b"do not replace"
        )

        archive_before = self.archive.read_bytes()
        rotation_destination = self.root / "existing-rotation.rtrk"
        rotation_destination.write_bytes(b"do not replace recovery")
        with self.assertRaises(secure_engine.RecoveryKeyError):
            secure_engine.rotate_recovery_key(
                self.archive,
                rotation_destination,
                current_recovery_key=self.recovery,
            )
        self.assertEqual(self.archive.read_bytes(), archive_before)
        self.assertEqual(
            rotation_destination.read_bytes(), b"do not replace recovery"
        )

    def test_password_policy_and_path_aliases_fail_before_publication(self) -> None:
        source = self.root / "source.gmw"
        source.write_bytes(b"source")
        output = self.root / "output.gmw"
        recovery = self.root / "output.rtrk"
        with self.assertRaises(secure_engine.SecureArchiveError):
            secure_engine.encrypt_file(
                source,
                output,
                password="too short",
                recovery_key_output=recovery,
            )
        self.assertFalse(output.exists())
        self.assertFalse(recovery.exists())

        with self.assertRaises(secure_engine.SecureArchiveError):
            secure_engine.encrypt_file(
                source,
                source,
                password=PASSWORD,
                recovery_key_output=recovery,
            )
        self.assertEqual(source.read_bytes(), b"source")
        self.assertFalse(recovery.exists())


if __name__ == "__main__":
    unittest.main()
