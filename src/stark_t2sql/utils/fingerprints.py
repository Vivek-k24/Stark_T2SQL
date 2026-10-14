"""Deterministic source fingerprints for later policy, context and trace owners.

These helpers describe future runtime reads only. They never supply a digest for
an unavailable artifact. Policy YAML is hashed as exact file bytes, without
parsing, rewriting or substituting fixture metadata.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from stark_t2sql.errors import (
    ConfigurationError,
    MissingDependencyError,
    SourceReadError,
)


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 hex digest of the supplied exact bytes."""
    if data is None:
        raise MissingDependencyError("Fingerprint source bytes are unavailable.")
    if not isinstance(data, bytes):
        raise ConfigurationError("Fingerprint source must be supplied as bytes.")
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1_048_576) -> str:
    """Hash a required file in binary mode without newline or encoding changes.

    Later callers must record a missing dependency as unavailable; they must not
    replace this exception with an empty-file digest or an invented fixture hash.
    A real, readable empty file does have its ordinary SHA-256 digest.
    """
    if path is None or path == "":
        raise MissingDependencyError("Fingerprint source path is unavailable.")
    if not isinstance(path, (str, Path)):
        raise ConfigurationError("Fingerprint source path must be text or a Path.")
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
        raise ConfigurationError("Fingerprint chunk size must be a positive integer.")

    source_path = Path(path)
    digest = hashlib.sha256()
    try:
        with source_path.open("rb") as source:
            while block := source.read(chunk_size):
                digest.update(block)
    except FileNotFoundError as exc:
        raise MissingDependencyError(
            f"Required fingerprint source file is unavailable: {source_path}"
        ) from exc
    except (OSError, ValueError) as exc:
        raise SourceReadError(
            f"Required fingerprint source file could not be read: {source_path}"
        ) from exc
    return digest.hexdigest()


def sha256_policy_yaml(path: str | Path) -> str:
    """Hash authoritative policy YAML byte for byte, including its formatting.

    The later policy loader owns YAML interpretation. This digest deliberately
    changes when comments, ordering, line endings or any other source byte changes.
    """
    return sha256_file(path)


def sha256_context(context: str) -> str:
    """Hash the exact emitted context using strict UTF-8 without a byte-order mark.

    The later context compiler owns deterministic ordering and serialization.
    This helper performs no Unicode, whitespace or newline normalization, so the
    digest describes the exact text emitted by that compiler.
    """
    if context is None:
        raise MissingDependencyError("Emitted context is unavailable.")
    if not isinstance(context, str):
        raise ConfigurationError("Emitted context must be supplied as text.")
    try:
        encoded = context.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise SourceReadError("Emitted context cannot be represented as strict UTF-8.") from exc
    return sha256_bytes(encoded)
