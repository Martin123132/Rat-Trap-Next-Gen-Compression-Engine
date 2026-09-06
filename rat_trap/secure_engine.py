"""Authenticated encryption envelope for portable Rat-Trap archives.

The secure envelope deliberately wraps an already complete ``.gmw`` archive
instead of changing any preserved GMW family.  All inner archive metadata,
paths, searchable text and structured tables are encrypted.  The small outer
header exposes only the envelope version, cipher/KDF parameters and sizes
needed to parse the file.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import math
import os
import shutil
import struct
import tempfile
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Optional

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCMSIV
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


SECURE_FORMAT = "RAT-TRAP-ENCRYPTED-1"
SECURE_SCHEMA_VERSION = 1
RECOVERY_FILE_FORMAT = "RAT-TRAP-RECOVERY-KEY-1"
RECOVERY_FILE_SCHEMA_VERSION = 1
SEALED_METADATA_FORMAT = "RAT-TRAP-SEALED-METADATA-1"
WRITER_VERSION = "5.7.0"

SECURE_MAGIC = b"RAT-TRAP-SECURE-1\x00"
_HEADER_LENGTH = struct.Struct("<I")
_MAX_HEADER_BYTES = 256 * 1024
_MAX_PASSWORD_BYTES = 4096
_MIN_NEW_PASSWORD_CHARACTERS = 15
_MIN_CHUNK_SIZE = 64 * 1024
_MAX_CHUNK_SIZE = 16 * 1024 * 1024
_MAX_CREATED_AT_NS = 2**63 - 1
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024

_ARGON2_MEMORY_KIB = 64 * 1024
_ARGON2_ITERATIONS = 3
_ARGON2_LANES = 4
_KEY_BYTES = 32
_SALT_BYTES = 16
_NONCE_BYTES = 12
_TAG_BYTES = 16
_RECOVERY_CHECKSUM_BYTES = 4
_SEALED_METADATA_CIPHERTEXT_BYTES = 141
_RECOVERY_PREFIX = "RTRK1"
_HEX = frozenset("0123456789abcdef")

_CIPHER_NAME = "AES-256-GCM-SIV"
_PASSWORD_KDF_NAME = "argon2id-rfc9106-low-memory"
_RECOVERY_KDF_NAME = "hkdf-sha256"
_RECOVERY_KDF_INFO = "rat-trap-recovery-slot-v1"

_DATA_CONTEXT_PREFIX = b"Rat-Trap secure data context v1\x00"
_METADATA_AAD_PREFIX = b"Rat-Trap sealed metadata v1\x00"
_SLOT_AAD_PREFIX = b"Rat-Trap key slot v1\x00"
_HEADER_AAD_PREFIX = b"Rat-Trap secure header v1\x00"
_CHUNK_AAD_PREFIX = b"Rat-Trap secure chunk v1\x00"
_PASSWORD_AD_PREFIX = b"Rat-Trap password KDF v1\x00"
_RECOVERY_CHECKSUM_PREFIX = b"Rat-Trap recovery key v1\x00"


class SecureArchiveError(ValueError):
    """Base error for invalid, damaged or unsafe encrypted archives."""


class UnlockRequiredError(SecureArchiveError):
    """Raised when an encrypted archive operation has no credential."""


class UnlockError(SecureArchiveError):
    """Raised when a supplied password or recovery key cannot unlock a file."""


class RecoveryKeyError(SecureArchiveError):
    """Raised when a recovery key file or human-readable code is invalid."""


@dataclass(frozen=True)
class SecureFileInfo:
    path: str
    format: str
    schema_version: int
    writer_version: str
    file_id: str
    created_at_ns: int
    cipher: str
    chunk_size: int
    chunk_count: int
    plaintext_size: int
    encrypted_size: int
    password_slot_count: int
    recovery_slot_count: int
    verified: bool = False

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class EncryptResult:
    secure_file: SecureFileInfo
    recovery_key_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "secure_file": self.secure_file.as_dict(),
            "recovery_key_path": self.recovery_key_path,
        }


@dataclass(frozen=True)
class DecryptResult:
    secure_file: SecureFileInfo
    output: str
    plaintext_sha256: str

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class RecoveryRotationResult:
    secure_file: SecureFileInfo
    recovery_key_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "secure_file": self.secure_file.as_dict(),
            "recovery_key_path": self.recovery_key_path,
        }


@dataclass(frozen=True)
class _UnlockedHeader:
    header: dict[str, object]
    data_key: bytes
    data_context: bytes
    plaintext_sha256: str
    data_offset: int
    info: SecureFileInfo


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number is not permitted: {value}")


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: object, *, label: str, expected: Optional[int] = None) -> bytes:
    if not isinstance(value, str):
        raise SecureArchiveError(f"Encrypted archive {label} is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise SecureArchiveError(
            f"Encrypted archive {label} is not valid Base64"
        ) from exc
    if _b64(decoded) != value:
        raise SecureArchiveError(
            f"Encrypted archive {label} is not canonical Base64"
        )
    if expected is not None and len(decoded) != expected:
        raise SecureArchiveError(
            f"Encrypted archive {label} must contain {expected} bytes"
        )
    return decoded


def _is_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in _HEX for character in value)
    )


def _require_exact_keys(
    value: object, keys: set[str], *, label: str
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SecureArchiveError(f"Encrypted archive {label} shape is invalid")
    return value


def _read_exact(handle: BinaryIO, size: int, *, label: str) -> bytes:
    value = handle.read(size)
    if len(value) != size:
        raise SecureArchiveError(f"Encrypted archive ended inside {label}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _validate_password(
    password: str, *, creating: bool
) -> bytes:
    if not isinstance(password, str):
        raise TypeError("Password must be text")
    try:
        normalized = unicodedata.normalize("NFC", password)
        encoded = normalized.encode("utf-8")
    except UnicodeError as exc:
        raise SecureArchiveError(
            "Password contains invalid Unicode text"
        ) from exc
    if not encoded:
        raise SecureArchiveError("Password cannot be empty")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        raise SecureArchiveError("Password is too long")
    if creating and len(normalized) < _MIN_NEW_PASSWORD_CHARACTERS:
        raise SecureArchiveError(
            "Use a password or passphrase containing at least "
            f"{_MIN_NEW_PASSWORD_CHARACTERS} characters"
        )
    return encoded


def validate_new_password(password: str) -> None:
    """Validate a new archive password before any plaintext work begins."""

    _validate_password(password, creating=True)


def _argon2_key(password: bytes, salt: bytes, file_id: str) -> bytes:
    try:
        return Argon2id(
            salt=salt,
            length=_KEY_BYTES,
            iterations=_ARGON2_ITERATIONS,
            lanes=_ARGON2_LANES,
            memory_cost=_ARGON2_MEMORY_KIB,
            ad=_PASSWORD_AD_PREFIX + bytes.fromhex(file_id),
            secret=None,
        ).derive(password)
    except (MemoryError, UnsupportedAlgorithm) as exc:
        raise SecureArchiveError(
            "This system cannot run the required Argon2id password KDF"
        ) from exc


def _recovery_kek(recovery_key: bytes, salt: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=salt,
        info=_RECOVERY_KDF_INFO.encode("ascii"),
    ).derive(recovery_key)


def _recovery_checksum(key: bytes) -> bytes:
    return hashlib.sha256(_RECOVERY_CHECKSUM_PREFIX + key).digest()[
        :_RECOVERY_CHECKSUM_BYTES
    ]


def encode_recovery_key(key: bytes) -> str:
    if not isinstance(key, bytes) or len(key) != _KEY_BYTES:
        raise RecoveryKeyError("A recovery key must contain exactly 32 bytes")
    encoded = base64.b32encode(key + _recovery_checksum(key)).decode("ascii")
    encoded = encoded.rstrip("=")
    groups = [encoded[index : index + 4] for index in range(0, len(encoded), 4)]
    return _RECOVERY_PREFIX + "-" + "-".join(groups)


def decode_recovery_key(value: str) -> bytes:
    if not isinstance(value, str):
        raise RecoveryKeyError("This is not a valid Rat-Trap recovery key")
    compact = "".join(
        character
        for character in value.upper()
        if character not in {"-", " ", "\t", "\r", "\n"}
    )
    if not compact.startswith(_RECOVERY_PREFIX):
        raise RecoveryKeyError("This is not a valid Rat-Trap recovery key")
    encoded = compact[len(_RECOVERY_PREFIX) :]
    padding = "=" * ((8 - len(encoded) % 8) % 8)
    try:
        payload = base64.b32decode(encoded + padding, casefold=True)
    except (ValueError, TypeError) as exc:
        raise RecoveryKeyError(
            "This is not a valid Rat-Trap recovery key"
        ) from exc
    if len(payload) != _KEY_BYTES + _RECOVERY_CHECKSUM_BYTES:
        raise RecoveryKeyError("This is not a valid Rat-Trap recovery key")
    key = payload[:_KEY_BYTES]
    checksum = payload[_KEY_BYTES:]
    if not hmac.compare_digest(checksum, _recovery_checksum(key)):
        raise RecoveryKeyError(
            "The Rat-Trap recovery key contains a transcription error"
        )
    return key


def write_recovery_key_file(
    path: Path,
    *,
    file_id: str,
    recovery_key: bytes,
    created_at_ns: Optional[int] = None,
) -> Path:
    if not _is_hex(file_id, 32):
        raise RecoveryKeyError("Recovery key file id is invalid")
    payload = {
        "format": RECOVERY_FILE_FORMAT,
        "schema_version": RECOVERY_FILE_SCHEMA_VERSION,
        "file_id": file_id,
        "created_at_ns": (
            time.time_ns() if created_at_ns is None else int(created_at_ns)
        ),
        "recovery_key": encode_recovery_key(recovery_key),
    }
    encoded = _canonical_json(payload) + b"\n"
    path = Path(path).resolve()
    if path.exists():
        raise RecoveryKeyError(
            f"Refusing to overwrite an existing recovery key: {path}"
        )
    staged = _staging_path(path, "recovery")
    published = False
    try:
        with open(staged, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        loaded_id, loaded_key = read_recovery_key_file(staged)
        if loaded_id != file_id or not hmac.compare_digest(
            loaded_key, recovery_key
        ):
            raise RecoveryKeyError("Recovery key file verification failed")
        _publish_new(staged, path)
        published = True
        loaded_id, loaded_key = read_recovery_key_file(path)
        if loaded_id != file_id or not hmac.compare_digest(
            loaded_key, recovery_key
        ):
            raise RecoveryKeyError("Recovery key file verification failed")
    except Exception:
        try:
            staged.unlink()
        except OSError:
            pass
        if published:
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return path


def read_recovery_key_file(path: Path) -> tuple[str, bytes]:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RecoveryKeyError(
            f"Could not read the Rat-Trap recovery key file: {path}"
        ) from exc
    if len(raw) > 16 * 1024:
        raise RecoveryKeyError("This is not a valid Rat-Trap recovery key file")
    canonical_source = raw[:-1] if raw.endswith(b"\n") else raw
    try:
        payload = json.loads(
            canonical_source.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
        canonical_payload = _canonical_json(payload)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise RecoveryKeyError(
            "This is not a valid Rat-Trap recovery key file"
        ) from exc
    try:
        payload = _require_exact_keys(
            payload,
            {
                "format",
                "schema_version",
                "file_id",
                "created_at_ns",
                "recovery_key",
            },
            label="recovery key file",
        )
    except SecureArchiveError as exc:
        raise RecoveryKeyError(
            "This is not a valid Rat-Trap recovery key file"
        ) from exc
    if (
        payload["format"] != RECOVERY_FILE_FORMAT
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != RECOVERY_FILE_SCHEMA_VERSION
        or not _is_hex(payload["file_id"], 32)
        or type(payload["created_at_ns"]) is not int
        or payload["created_at_ns"] <= 0
        or payload["created_at_ns"] > _MAX_CREATED_AT_NS
        or not isinstance(payload["recovery_key"], str)
        or canonical_payload != canonical_source
    ):
        raise RecoveryKeyError("This is not a valid Rat-Trap recovery key file")
    recovery_key = decode_recovery_key(payload["recovery_key"])
    if encode_recovery_key(recovery_key) != payload["recovery_key"]:
        raise RecoveryKeyError(
            "This is not a canonical Rat-Trap recovery key file"
        )
    return str(payload["file_id"]), recovery_key


def is_encrypted_archive(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(len(SECURE_MAGIC)) == SECURE_MAGIC
    except OSError:
        return False


def _base_descriptor(header: dict[str, object]) -> dict[str, object]:
    return {
        "format": header["format"],
        "schema_version": header["schema_version"],
        "writer_version": header["writer_version"],
        "file_id": header["file_id"],
        "created_at_ns": header["created_at_ns"],
        "cipher": header["cipher"],
        "chunk_size": header["chunk_size"],
        "chunk_count": header["chunk_count"],
        "plaintext_size": header["plaintext_size"],
    }


def _data_context(header: dict[str, object]) -> bytes:
    return hashlib.sha256(
        _DATA_CONTEXT_PREFIX + _canonical_json(_base_descriptor(header))
    ).digest()


def _slot_descriptor(slot: dict[str, object]) -> dict[str, object]:
    return {
        "slot_id": slot["slot_id"],
        "type": slot["type"],
        "kdf": slot["kdf"],
    }


def _slot_aad(
    slot: dict[str, object], data_context: bytes
) -> bytes:
    return (
        _SLOT_AAD_PREFIX
        + data_context
        + _canonical_json(_slot_descriptor(slot))
    )


def _new_password_slot(
    data_key: bytes,
    password: str,
    *,
    file_id: str,
    data_context: bytes,
) -> dict[str, object]:
    password_bytes = _validate_password(password, creating=True)
    salt = os.urandom(_SALT_BYTES)
    slot: dict[str, object] = {
        "slot_id": uuid.uuid4().hex,
        "type": "password",
        "kdf": {
            "name": _PASSWORD_KDF_NAME,
            "salt": _b64(salt),
            "length": _KEY_BYTES,
            "memory_kib": _ARGON2_MEMORY_KIB,
            "iterations": _ARGON2_ITERATIONS,
            "lanes": _ARGON2_LANES,
        },
    }
    kek = _argon2_key(password_bytes, salt, file_id)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCMSIV(kek).encrypt(
        nonce, data_key, _slot_aad(slot, data_context)
    )
    slot["wrap"] = {
        "cipher": _CIPHER_NAME,
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
    }
    return slot


def _new_recovery_slot(
    data_key: bytes,
    recovery_key: bytes,
    *,
    data_context: bytes,
) -> dict[str, object]:
    if len(recovery_key) != _KEY_BYTES:
        raise RecoveryKeyError("Recovery key length is invalid")
    salt = os.urandom(_KEY_BYTES)
    slot: dict[str, object] = {
        "slot_id": uuid.uuid4().hex,
        "type": "recovery",
        "kdf": {
            "name": _RECOVERY_KDF_NAME,
            "salt": _b64(salt),
            "length": _KEY_BYTES,
            "info": _RECOVERY_KDF_INFO,
        },
    }
    kek = _recovery_kek(recovery_key, salt)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCMSIV(kek).encrypt(
        nonce, data_key, _slot_aad(slot, data_context)
    )
    slot["wrap"] = {
        "cipher": _CIPHER_NAME,
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
    }
    return slot


def _header_without_auth(
    header: dict[str, object]
) -> dict[str, object]:
    return {
        key: value
        for key, value in header.items()
        if key != "header_auth"
    }


def _new_header_auth(
    header_without_auth: dict[str, object], data_key: bytes
) -> dict[str, object]:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCMSIV(data_key).encrypt(
        nonce,
        b"",
        _HEADER_AAD_PREFIX + _canonical_json(header_without_auth),
    )
    return {
        "cipher": _CIPHER_NAME,
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
    }


def _validate_wrap(value: object, *, label: str) -> dict[str, object]:
    wrap = _require_exact_keys(
        value,
        {"cipher", "nonce", "ciphertext"},
        label=label,
    )
    if wrap["cipher"] != _CIPHER_NAME:
        raise SecureArchiveError(f"Encrypted archive {label} cipher is unsupported")
    _unb64(wrap["nonce"], label=f"{label} nonce", expected=_NONCE_BYTES)
    return wrap


def _validate_slot(value: object) -> dict[str, object]:
    slot = _require_exact_keys(
        value,
        {"slot_id", "type", "kdf", "wrap"},
        label="key slot",
    )
    if not _is_hex(slot["slot_id"], 32):
        raise SecureArchiveError("Encrypted archive key slot id is invalid")
    slot_type = slot["type"]
    if slot_type == "password":
        kdf = _require_exact_keys(
            slot["kdf"],
            {
                "name",
                "salt",
                "length",
                "memory_kib",
                "iterations",
                "lanes",
            },
            label="password KDF",
        )
        if (
            kdf["name"] != _PASSWORD_KDF_NAME
            or type(kdf["length"]) is not int
            or kdf["length"] != _KEY_BYTES
            or type(kdf["memory_kib"]) is not int
            or kdf["memory_kib"] != _ARGON2_MEMORY_KIB
            or type(kdf["iterations"]) is not int
            or kdf["iterations"] != _ARGON2_ITERATIONS
            or type(kdf["lanes"]) is not int
            or kdf["lanes"] != _ARGON2_LANES
        ):
            raise SecureArchiveError(
                "Encrypted archive password KDF parameters are unsupported"
            )
        _unb64(kdf["salt"], label="password KDF salt", expected=_SALT_BYTES)
    elif slot_type == "recovery":
        kdf = _require_exact_keys(
            slot["kdf"],
            {"name", "salt", "length", "info"},
            label="recovery KDF",
        )
        if (
            kdf["name"] != _RECOVERY_KDF_NAME
            or type(kdf["length"]) is not int
            or kdf["length"] != _KEY_BYTES
            or kdf["info"] != _RECOVERY_KDF_INFO
        ):
            raise SecureArchiveError(
                "Encrypted archive recovery KDF parameters are unsupported"
            )
        _unb64(kdf["salt"], label="recovery KDF salt", expected=_KEY_BYTES)
    else:
        raise SecureArchiveError("Encrypted archive key slot type is unsupported")
    wrap = _validate_wrap(slot["wrap"], label="key slot wrap")
    _unb64(
        wrap["ciphertext"],
        label="key slot ciphertext",
        expected=_KEY_BYTES + _TAG_BYTES,
    )
    return slot


def _read_header(
    path: Path,
) -> tuple[dict[str, object], bytes, int, int]:
    path = Path(path)
    try:
        encrypted_size = path.stat().st_size
        with open(path, "rb") as handle:
            if _read_exact(
                handle, len(SECURE_MAGIC), label="format marker"
            ) != SECURE_MAGIC:
                raise SecureArchiveError(
                    f"Not a Rat-Trap encrypted archive: {path}"
                )
            header_length = _HEADER_LENGTH.unpack(
                _read_exact(
                    handle, _HEADER_LENGTH.size, label="header length"
                )
            )[0]
            if header_length < 2 or header_length > _MAX_HEADER_BYTES:
                raise SecureArchiveError(
                    "Encrypted archive header length is unsafe"
                )
            header_bytes = _read_exact(
                handle, header_length, label="security header"
            )
            data_offset = handle.tell()
    except OSError as exc:
        raise SecureArchiveError(
            f"Could not read encrypted archive: {path}"
        ) from exc
    try:
        header = json.loads(
            header_bytes.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
        canonical_header = _canonical_json(header)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SecureArchiveError(
            "Encrypted archive security header is invalid"
        ) from exc
    header = _require_exact_keys(
        header,
        {
            "format",
            "schema_version",
            "writer_version",
            "file_id",
            "created_at_ns",
            "cipher",
            "chunk_size",
            "chunk_count",
            "plaintext_size",
            "sealed_metadata",
            "key_slots",
            "header_auth",
        },
        label="header",
    )
    if canonical_header != header_bytes:
        raise SecureArchiveError(
            "Encrypted archive header is not canonical JSON"
        )
    if (
        header["format"] != SECURE_FORMAT
        or type(header["schema_version"]) is not int
        or header["schema_version"] != SECURE_SCHEMA_VERSION
        or not isinstance(header["writer_version"], str)
        or not _is_hex(header["file_id"], 32)
        or type(header["created_at_ns"]) is not int
        or header["created_at_ns"] <= 0
        or header["created_at_ns"] > _MAX_CREATED_AT_NS
        or header["cipher"] != _CIPHER_NAME
        or type(header["chunk_size"]) is not int
        or not _MIN_CHUNK_SIZE
        <= int(header["chunk_size"])
        <= _MAX_CHUNK_SIZE
        or type(header["plaintext_size"]) is not int
        or int(header["plaintext_size"]) < 0
        or int(header["plaintext_size"]) > (2**63 - 1)
        or type(header["chunk_count"]) is not int
        or int(header["chunk_count"]) < 0
        or int(header["chunk_count"]) > (2**32 - 1)
    ):
        raise SecureArchiveError(
            "Encrypted archive header values are invalid or unsupported"
        )
    expected_chunks = (
        math.ceil(int(header["plaintext_size"]) / int(header["chunk_size"]))
        if int(header["plaintext_size"])
        else 0
    )
    if int(header["chunk_count"]) != expected_chunks:
        raise SecureArchiveError("Encrypted archive chunk count is invalid")
    sealed = _validate_wrap(
        header["sealed_metadata"], label="sealed metadata"
    )
    _unb64(
        sealed["ciphertext"],
        label="sealed metadata ciphertext",
        expected=_SEALED_METADATA_CIPHERTEXT_BYTES,
    )
    slots_value = header["key_slots"]
    if not isinstance(slots_value, list) or len(slots_value) != 2:
        raise SecureArchiveError(
            "Encrypted archive must contain password and recovery key slots"
        )
    slots = [_validate_slot(value) for value in slots_value]
    if sorted(str(slot["type"]) for slot in slots) != [
        "password",
        "recovery",
    ]:
        raise SecureArchiveError(
            "Encrypted archive key slot set is invalid"
        )
    slot_ids = [str(slot["slot_id"]) for slot in slots]
    if len(set(slot_ids)) != len(slot_ids):
        raise SecureArchiveError(
            "Encrypted archive contains duplicate key slot ids"
        )
    auth = _validate_wrap(header["header_auth"], label="header authentication")
    _unb64(
        auth["ciphertext"],
        label="header authentication tag",
        expected=_TAG_BYTES,
    )
    expected_size = (
        data_offset
        + int(header["plaintext_size"])
        + int(header["chunk_count"]) * (_NONCE_BYTES + _TAG_BYTES)
    )
    if encrypted_size != expected_size:
        if encrypted_size < expected_size:
            raise SecureArchiveError("Encrypted archive is truncated")
        raise SecureArchiveError("Encrypted archive contains trailing data")
    return header, header_bytes, data_offset, encrypted_size


def _info_from_header(
    path: Path,
    header: dict[str, object],
    encrypted_size: int,
    *,
    verified: bool,
) -> SecureFileInfo:
    slots = list(header["key_slots"])  # type: ignore[arg-type]
    return SecureFileInfo(
        path=str(Path(path).resolve()),
        format=str(header["format"]),
        schema_version=int(header["schema_version"]),
        writer_version=str(header["writer_version"]),
        file_id=str(header["file_id"]),
        created_at_ns=int(header["created_at_ns"]),
        cipher=str(header["cipher"]),
        chunk_size=int(header["chunk_size"]),
        chunk_count=int(header["chunk_count"]),
        plaintext_size=int(header["plaintext_size"]),
        encrypted_size=encrypted_size,
        password_slot_count=sum(
            1 for slot in slots if slot["type"] == "password"
        ),
        recovery_slot_count=sum(
            1 for slot in slots if slot["type"] == "recovery"
        ),
        verified=verified,
    )


def read_secure_info(path: Path) -> SecureFileInfo:
    header, _, _, encrypted_size = _read_header(Path(path))
    return _info_from_header(
        Path(path), header, encrypted_size, verified=False
    )


def _credential_recovery_key(
    recovery_key: Optional[str | bytes | Path],
    *,
    expected_file_id: str,
) -> Optional[bytes]:
    if recovery_key is None:
        return None
    if isinstance(recovery_key, Path):
        file_id, key = read_recovery_key_file(recovery_key)
        if file_id != expected_file_id:
            raise RecoveryKeyError(
                "This recovery key belongs to a different encrypted archive"
            )
        return key
    if isinstance(recovery_key, bytes):
        if len(recovery_key) != _KEY_BYTES:
            raise RecoveryKeyError(
                "This is not a valid Rat-Trap recovery key"
            )
        return recovery_key
    if isinstance(recovery_key, str):
        possible_path = Path(recovery_key)
        if possible_path.is_file():
            file_id, key = read_recovery_key_file(possible_path)
            if file_id != expected_file_id:
                raise RecoveryKeyError(
                    "This recovery key belongs to a different encrypted archive"
                )
            return key
        return decode_recovery_key(recovery_key)
    raise TypeError("Recovery key must be a key code, bytes, or file path")


def _unwrap_data_key(
    header: dict[str, object],
    *,
    password: Optional[str],
    recovery_key: Optional[str | bytes | Path],
    data_context: bytes,
) -> bytes:
    if (password is None) == (recovery_key is None):
        raise UnlockRequiredError(
            "Provide exactly one password or recovery key"
        )
    slots = list(header["key_slots"])  # type: ignore[arg-type]
    slot_type = "password" if password is not None else "recovery"
    slot = next(
        (value for value in slots if value["type"] == slot_type),
        None,
    )
    if slot is None:
        raise UnlockError(
            f"Encrypted archive has no active {slot_type} key slot"
        )
    kdf = slot["kdf"]
    try:
        if password is not None:
            password_bytes = _validate_password(password, creating=False)
            salt = _unb64(
                kdf["salt"], label="password KDF salt", expected=_SALT_BYTES
            )
            kek = _argon2_key(
                password_bytes, salt, str(header["file_id"])
            )
        else:
            key = _credential_recovery_key(
                recovery_key, expected_file_id=str(header["file_id"])
            )
            assert key is not None
            salt = _unb64(
                kdf["salt"], label="recovery KDF salt", expected=_KEY_BYTES
            )
            kek = _recovery_kek(key, salt)
        wrap = slot["wrap"]
        nonce = _unb64(
            wrap["nonce"], label="key slot nonce", expected=_NONCE_BYTES
        )
        ciphertext = _unb64(
            wrap["ciphertext"],
            label="key slot ciphertext",
            expected=_KEY_BYTES + _TAG_BYTES,
        )
        return AESGCMSIV(kek).decrypt(
            nonce, ciphertext, _slot_aad(slot, data_context)
        )
    except InvalidTag as exc:
        if password is not None:
            message = (
                "Could not unlock this archive with that password. "
                "Try again or use its recovery key."
            )
        else:
            message = (
                "This recovery key is not active for this encrypted archive"
            )
        raise UnlockError(message) from exc


def _unlock_header(
    path: Path,
    *,
    password: Optional[str] = None,
    recovery_key: Optional[str | bytes | Path] = None,
) -> _UnlockedHeader:
    header, _, data_offset, encrypted_size = _read_header(path)
    context = _data_context(header)
    data_key = _unwrap_data_key(
        header,
        password=password,
        recovery_key=recovery_key,
        data_context=context,
    )
    auth = header["header_auth"]
    try:
        authenticated = AESGCMSIV(data_key).decrypt(
            _unb64(
                auth["nonce"],
                label="header authentication nonce",
                expected=_NONCE_BYTES,
            ),
            _unb64(
                auth["ciphertext"],
                label="header authentication tag",
                expected=_TAG_BYTES,
            ),
            _HEADER_AAD_PREFIX
            + _canonical_json(_header_without_auth(header)),
        )
    except InvalidTag as exc:
        raise SecureArchiveError(
            "Encrypted archive security metadata failed authentication"
        ) from exc
    if authenticated:
        raise SecureArchiveError(
            "Encrypted archive header authentication payload is invalid"
        )
    sealed = header["sealed_metadata"]
    try:
        metadata_bytes = AESGCMSIV(data_key).decrypt(
            _unb64(
                sealed["nonce"],
                label="sealed metadata nonce",
                expected=_NONCE_BYTES,
            ),
            _unb64(
                sealed["ciphertext"],
                label="sealed metadata ciphertext",
            ),
            _METADATA_AAD_PREFIX + context,
        )
    except InvalidTag as exc:
        raise SecureArchiveError(
            "Encrypted archive sealed metadata failed authentication"
        ) from exc
    try:
        metadata = json.loads(
            metadata_bytes.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
        canonical_metadata = _canonical_json(metadata)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SecureArchiveError(
            "Encrypted archive sealed metadata is invalid"
        ) from exc
    metadata = _require_exact_keys(
        metadata,
        {"format", "plaintext_sha256"},
        label="sealed metadata",
    )
    if (
        metadata["format"] != SEALED_METADATA_FORMAT
        or not _is_hex(metadata["plaintext_sha256"], 64)
        or canonical_metadata != metadata_bytes
    ):
        raise SecureArchiveError(
            "Encrypted archive sealed metadata values are invalid"
        )
    return _UnlockedHeader(
        header=header,
        data_key=data_key,
        data_context=context,
        plaintext_sha256=str(metadata["plaintext_sha256"]),
        data_offset=data_offset,
        info=_info_from_header(
            path, header, encrypted_size, verified=False
        ),
    )


def _chunk_aad(
    data_context: bytes, index: int, plaintext_size: int
) -> bytes:
    return (
        _CHUNK_AAD_PREFIX
        + data_context
        + int(index).to_bytes(8, "little")
        + int(plaintext_size).to_bytes(8, "little")
    )


def _iter_decrypted_chunks(
    path: Path, unlocked: _UnlockedHeader
) -> Iterator[bytes]:
    header = unlocked.header
    remaining = int(header["plaintext_size"])
    chunk_size = int(header["chunk_size"])
    try:
        with open(path, "rb") as handle:
            handle.seek(unlocked.data_offset)
            cipher = AESGCMSIV(unlocked.data_key)
            for index in range(int(header["chunk_count"])):
                expected = min(chunk_size, remaining)
                nonce = _read_exact(
                    handle, _NONCE_BYTES, label=f"chunk {index} nonce"
                )
                ciphertext = _read_exact(
                    handle,
                    expected + _TAG_BYTES,
                    label=f"chunk {index} ciphertext",
                )
                try:
                    plaintext = cipher.decrypt(
                        nonce,
                        ciphertext,
                        _chunk_aad(
                            unlocked.data_context, index, expected
                        ),
                    )
                except InvalidTag as exc:
                    raise SecureArchiveError(
                        f"Encrypted archive chunk {index} failed authentication"
                    ) from exc
                if len(plaintext) != expected:
                    raise SecureArchiveError(
                        f"Encrypted archive chunk {index} length is invalid"
                    )
                remaining -= len(plaintext)
                yield plaintext
            if remaining != 0:
                raise SecureArchiveError(
                    "Encrypted archive plaintext length is incomplete"
                )
            if handle.read(1):
                raise SecureArchiveError(
                    "Encrypted archive contains trailing data"
                )
    except OSError as exc:
        raise SecureArchiveError(
            f"Could not read encrypted archive payload: {path}"
        ) from exc


def verify_encrypted_file(
    path: Path,
    *,
    password: Optional[str] = None,
    recovery_key: Optional[str | bytes | Path] = None,
) -> SecureFileInfo:
    path = Path(path).resolve()
    unlocked = _unlock_header(
        path, password=password, recovery_key=recovery_key
    )
    digest = hashlib.sha256()
    total = 0
    for block in _iter_decrypted_chunks(path, unlocked):
        digest.update(block)
        total += len(block)
    if total != unlocked.info.plaintext_size:
        raise SecureArchiveError(
            "Encrypted archive plaintext size verification failed"
        )
    if not hmac.compare_digest(
        digest.hexdigest(), unlocked.plaintext_sha256
    ):
        raise SecureArchiveError(
            "Encrypted archive plaintext checksum verification failed"
        )
    return dataclasses.replace(unlocked.info, verified=True)


@contextmanager
def _credential_mutation_lock(path: Path) -> Iterator[None]:
    """Hold an OS-released lock for one archive's credential transaction."""
    path = Path(path).resolve()
    lock_path = path.with_name(
        f".{path.name}.rat-trap-credential-update.lock"
    )
    try:
        handle = open(lock_path, "a+b")
    except OSError as exc:
        raise SecureArchiveError(
            "Could not create the encrypted archive credential-update lock"
        ) from exc
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(
                    handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                )
        except OSError as exc:
            raise SecureArchiveError(
                "Another Rat-Trap credential update is already using "
                "this encrypted archive"
            ) from exc
        acquired = True
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                # Closing the descriptor also releases an OS-owned lock.
                pass
        handle.close()


def _staging_path(destination: Path, label: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.{label}-",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    return Path(name)


def _publish_new(staged: Path, destination: Path) -> None:
    if destination.exists():
        raise SecureArchiveError(
            f"Destination already exists: {destination}"
        )
    try:
        if os.name == "nt":
            # Staging is in the destination directory. Windows rename is a
            # same-volume atomic publication and refuses an existing target.
            os.rename(staged, destination)
        else:
            # A hard link is the portable POSIX no-replace primitive. Do not
            # fall back to copying into the final name: a crash could expose
            # a truncated archive as if it were complete.
            os.link(staged, destination)
            staged.unlink()
    except FileExistsError as exc:
        raise SecureArchiveError(
            f"Destination already exists: {destination}"
        ) from exc
    except OSError as exc:
        raise SecureArchiveError(
            "This filesystem could not atomically publish the encrypted "
            "file without replacing an existing destination"
        ) from exc


def _publish(
    staged: Path, destination: Path, *, replace: bool
) -> None:
    if replace:
        os.replace(staged, destination)
    else:
        _publish_new(staged, destination)


def _build_initial_header(
    *,
    plaintext_size: int,
    plaintext_sha256: str,
    chunk_size: int,
    password: str,
    data_key: bytes,
    recovery_key: bytes,
) -> dict[str, object]:
    header: dict[str, object] = {
        "format": SECURE_FORMAT,
        "schema_version": SECURE_SCHEMA_VERSION,
        "writer_version": WRITER_VERSION,
        "file_id": uuid.uuid4().hex,
        "created_at_ns": time.time_ns(),
        "cipher": _CIPHER_NAME,
        "chunk_size": chunk_size,
        "chunk_count": (
            math.ceil(plaintext_size / chunk_size)
            if plaintext_size
            else 0
        ),
        "plaintext_size": plaintext_size,
    }
    context = _data_context(header)
    metadata = {
        "format": SEALED_METADATA_FORMAT,
        "plaintext_sha256": plaintext_sha256,
    }
    metadata_nonce = os.urandom(_NONCE_BYTES)
    header["sealed_metadata"] = {
        "cipher": _CIPHER_NAME,
        "nonce": _b64(metadata_nonce),
        "ciphertext": _b64(
            AESGCMSIV(data_key).encrypt(
                metadata_nonce,
                _canonical_json(metadata),
                _METADATA_AAD_PREFIX + context,
            )
        ),
    }
    header["key_slots"] = [
        _new_password_slot(
            data_key,
            password,
            file_id=str(header["file_id"]),
            data_context=context,
        ),
        _new_recovery_slot(
            data_key,
            recovery_key,
            data_context=context,
        ),
    ]
    header["header_auth"] = _new_header_auth(
        _header_without_auth(header), data_key
    )
    return header


def encrypt_file(
    source: Path,
    output: Path,
    *,
    password: str,
    recovery_key_output: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    replace: bool = False,
    progress: Optional[Callable[[int, int], None]] = None,
    pre_publish_validator: Optional[Callable[[Path, Path], None]] = None,
) -> EncryptResult:
    source_argument = Path(source)
    output = Path(output).resolve()
    recovery_key_output = Path(recovery_key_output).resolve()
    if source_argument.is_symlink():
        raise SecureArchiveError(
            "Encrypted archive input cannot be a symbolic link"
        )
    source = source_argument.resolve()
    if not source.is_file():
        raise SecureArchiveError(f"Input file not found: {source}")
    if output == source or recovery_key_output in {source, output}:
        raise SecureArchiveError(
            "Input, encrypted output and recovery key paths must be different"
        )
    if not _MIN_CHUNK_SIZE <= chunk_size <= _MAX_CHUNK_SIZE:
        raise SecureArchiveError(
            f"Encryption chunk size must be between {_MIN_CHUNK_SIZE} "
            f"and {_MAX_CHUNK_SIZE} bytes"
        )
    _validate_password(password, creating=True)
    if recovery_key_output.exists():
        raise RecoveryKeyError(
            f"Refusing to overwrite an existing recovery key: "
            f"{recovery_key_output}"
        )
    if output.exists() and not replace:
        raise SecureArchiveError(f"Destination already exists: {output}")

    source_stat = source.stat()
    plaintext_size = source_stat.st_size
    plaintext_sha256 = _sha256_file(source)
    data_key = AESGCMSIV.generate_key(bit_length=256)
    recovery_key = os.urandom(_KEY_BYTES)
    header = _build_initial_header(
        plaintext_size=plaintext_size,
        plaintext_sha256=plaintext_sha256,
        chunk_size=chunk_size,
        password=password,
        data_key=data_key,
        recovery_key=recovery_key,
    )
    header_bytes = _canonical_json(header)
    if len(header_bytes) > _MAX_HEADER_BYTES:
        raise SecureArchiveError("Generated encrypted header is too large")

    staged = _staging_path(output, "encrypting")
    published_recovery = False
    try:
        digest = hashlib.sha256()
        total = 0
        with open(source, "rb") as source_handle, open(
            staged, "wb"
        ) as target:
            target.write(SECURE_MAGIC)
            target.write(_HEADER_LENGTH.pack(len(header_bytes)))
            target.write(header_bytes)
            cipher = AESGCMSIV(data_key)
            for index in range(int(header["chunk_count"])):
                block = source_handle.read(chunk_size)
                if not block:
                    raise SecureArchiveError(
                        "Input changed while it was being encrypted"
                    )
                nonce = os.urandom(_NONCE_BYTES)
                target.write(nonce)
                target.write(
                    cipher.encrypt(
                        nonce,
                        block,
                        _chunk_aad(
                            _data_context(header), index, len(block)
                        ),
                    )
                )
                digest.update(block)
                total += len(block)
                if progress is not None:
                    progress(total, plaintext_size)
            if source_handle.read(1):
                raise SecureArchiveError(
                    "Input changed while it was being encrypted"
                )
            target.flush()
            os.fsync(target.fileno())
        if (
            total != plaintext_size
            or digest.hexdigest() != plaintext_sha256
            or source.stat().st_size != source_stat.st_size
            or source.stat().st_mtime_ns != source_stat.st_mtime_ns
        ):
            raise SecureArchiveError(
                "Input changed while it was being encrypted"
            )
        verified = verify_encrypted_file(staged, password=password)
        write_recovery_key_file(
            recovery_key_output,
            file_id=verified.file_id,
            recovery_key=recovery_key,
            created_at_ns=verified.created_at_ns,
        )
        published_recovery = True
        recovery_verified = verify_encrypted_file(
            staged,
            recovery_key=recovery_key_output,
        )
        if recovery_verified.file_id != verified.file_id:
            raise SecureArchiveError(
                "Generated recovery key verification returned the wrong "
                "encrypted file identity"
            )
        if pre_publish_validator is not None:
            pre_publish_validator(staged, recovery_key_output)
        _publish(staged, output, replace=replace)
        verified = dataclasses.replace(
            recovery_verified,
            path=str(output),
            encrypted_size=output.stat().st_size,
        )
        return EncryptResult(
            secure_file=verified,
            recovery_key_path=str(recovery_key_output),
        )
    except Exception:
        try:
            staged.unlink()
        except OSError:
            pass
        if published_recovery and not output.exists():
            # The verified key is intentionally retained. It is safer to
            # leave an orphan recovery file than to risk deleting the only
            # recovery material during an uncertain publication failure.
            pass
        raise


def decrypt_file(
    source: Path,
    output: Path,
    *,
    password: Optional[str] = None,
    recovery_key: Optional[str | bytes | Path] = None,
    replace: bool = False,
    progress: Optional[Callable[[int, int], None]] = None,
) -> DecryptResult:
    source = Path(source).resolve()
    output = Path(output).resolve()
    if source == output:
        raise SecureArchiveError(
            "Encrypted input and plaintext output must be different"
        )
    if output.exists() and not replace:
        raise SecureArchiveError(f"Destination already exists: {output}")
    unlocked = _unlock_header(
        source, password=password, recovery_key=recovery_key
    )
    staged = _staging_path(output, "decrypting")
    try:
        digest = hashlib.sha256()
        total = 0
        with open(staged, "wb") as target:
            for block in _iter_decrypted_chunks(source, unlocked):
                target.write(block)
                digest.update(block)
                total += len(block)
                if progress is not None:
                    progress(total, unlocked.info.plaintext_size)
            target.flush()
            os.fsync(target.fileno())
        plaintext_sha256 = digest.hexdigest()
        if (
            total != unlocked.info.plaintext_size
            or not hmac.compare_digest(
                plaintext_sha256, unlocked.plaintext_sha256
            )
        ):
            raise SecureArchiveError(
                "Decrypted archive checksum verification failed"
            )
        _publish(staged, output, replace=replace)
        return DecryptResult(
            secure_file=dataclasses.replace(
                unlocked.info, verified=True
            ),
            output=str(output),
            plaintext_sha256=plaintext_sha256,
        )
    except Exception:
        try:
            staged.unlink()
        except OSError:
            pass
        raise


def _rewrite_header(
    path: Path,
    old: _UnlockedHeader,
    new_header: dict[str, object],
    *,
    verify_password: Optional[str] = None,
    verify_recovery_key: Optional[str | bytes | Path] = None,
) -> SecureFileInfo:
    path = Path(path).resolve()
    new_header["header_auth"] = _new_header_auth(
        _header_without_auth(new_header), old.data_key
    )
    encoded = _canonical_json(new_header)
    if len(encoded) > _MAX_HEADER_BYTES:
        raise SecureArchiveError("Updated encrypted header is too large")
    staged = _staging_path(path, "rewrapping")
    try:
        with open(path, "rb") as source, open(staged, "wb") as target:
            source.seek(old.data_offset)
            target.write(SECURE_MAGIC)
            target.write(_HEADER_LENGTH.pack(len(encoded)))
            target.write(encoded)
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        verified = verify_encrypted_file(
            staged,
            password=verify_password,
            recovery_key=verify_recovery_key,
        )
        staged_size = staged.stat().st_size
        current_header, current_bytes, current_offset, current_size = (
            _read_header(path)
        )
        expected_bytes = _canonical_json(old.header)
        if (
            current_offset != old.data_offset
            or current_size != old.info.encrypted_size
            or not hmac.compare_digest(current_bytes, expected_bytes)
            or current_header != old.header
        ):
            raise SecureArchiveError(
                "Encrypted archive changed during credential update; "
                "no stale update was committed"
            )
        committed = dataclasses.replace(
            verified,
            path=str(path),
            encrypted_size=staged_size,
        )
        os.replace(staged, path)
        return committed
    except Exception:
        try:
            staged.unlink()
        except OSError:
            pass
        raise


def change_password(
    path: Path,
    *,
    new_password: str,
    current_password: Optional[str] = None,
    recovery_key: Optional[str | bytes | Path] = None,
) -> SecureFileInfo:
    path = Path(path).resolve()
    _validate_password(new_password, creating=True)
    with _credential_mutation_lock(path):
        unlocked = _unlock_header(
            path, password=current_password, recovery_key=recovery_key
        )
        header = dict(unlocked.header)
        slots = [
            dict(slot)
            for slot in list(  # type: ignore[arg-type]
                header["key_slots"]
            )
        ]
        replacement = _new_password_slot(
            unlocked.data_key,
            new_password,
            file_id=str(header["file_id"]),
            data_context=unlocked.data_context,
        )
        header["key_slots"] = [
            replacement if slot["type"] == "password" else slot
            for slot in slots
        ]
        return _rewrite_header(
            path,
            unlocked,
            header,
            verify_password=new_password,
        )


def rotate_recovery_key(
    path: Path,
    new_recovery_key_output: Path,
    *,
    password: Optional[str] = None,
    current_recovery_key: Optional[str | bytes | Path] = None,
) -> RecoveryRotationResult:
    path = Path(path).resolve()
    new_recovery_key_output = Path(new_recovery_key_output).resolve()
    with _credential_mutation_lock(path):
        if new_recovery_key_output.exists():
            raise RecoveryKeyError(
                f"Refusing to overwrite an existing recovery key: "
                f"{new_recovery_key_output}"
            )
        unlocked = _unlock_header(
            path,
            password=password,
            recovery_key=current_recovery_key,
        )
        new_key = os.urandom(_KEY_BYTES)
        new_slot = _new_recovery_slot(
            unlocked.data_key,
            new_key,
            data_context=unlocked.data_context,
        )
        header = dict(unlocked.header)
        slots = [
            dict(slot)
            for slot in list(  # type: ignore[arg-type]
                header["key_slots"]
            )
        ]
        header["key_slots"] = [
            new_slot if slot["type"] == "recovery" else slot
            for slot in slots
        ]
        recovery_published = False
        try:
            write_recovery_key_file(
                new_recovery_key_output,
                file_id=str(header["file_id"]),
                recovery_key=new_key,
                created_at_ns=time.time_ns(),
            )
            recovery_published = True
            updated = _rewrite_header(
                path,
                unlocked,
                header,
                verify_recovery_key=new_recovery_key_output,
            )
        except Exception:
            if recovery_published:
                try:
                    new_recovery_key_output.unlink()
                except FileNotFoundError:
                    pass
                except OSError as cleanup_error:
                    raise SecureArchiveError(
                        "The archive credential update failed and its "
                        "uncommitted recovery key could not be removed"
                    ) from cleanup_error
            raise
        return RecoveryRotationResult(
            secure_file=updated,
            recovery_key_path=str(new_recovery_key_output),
        )


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DecryptResult",
    "EncryptResult",
    "RECOVERY_FILE_FORMAT",
    "RecoveryKeyError",
    "RecoveryRotationResult",
    "SECURE_FORMAT",
    "SecureArchiveError",
    "SecureFileInfo",
    "UnlockError",
    "UnlockRequiredError",
    "change_password",
    "decode_recovery_key",
    "decrypt_file",
    "encode_recovery_key",
    "encrypt_file",
    "is_encrypted_archive",
    "read_recovery_key_file",
    "read_secure_info",
    "rotate_recovery_key",
    "validate_new_password",
    "verify_encrypted_file",
    "write_recovery_key_file",
]
