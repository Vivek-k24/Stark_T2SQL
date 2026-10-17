"""Explicit local runtime artifacts, including private files outside Git.

No files are created/read and no service is contacted. Relative sources stay
inside the workspace; an external source needs an explicit absolute local path.
This selects bytes, not trust: each consumer still checks its actual contract,
digest, review and permissions. Frozen project sources remain workspace-only.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..errors import ConfigurationError


def resolve_runtime_path(path: str | Path, *, root: Path, label: str) -> Path:
    raw = str(path)
    if (not raw or "://" in raw or "\x00" in raw
            or raw.startswith(("\\\\", "//"))
            or re.match(r"^[A-Za-z]:(?![\\/])", raw)):
        raise ConfigurationError(f"The {label} requires an explicit local file path.")
    source = Path(raw)
    if not source.is_absolute() and (source.drive or source.root):
        raise ConfigurationError(f"The {label} requires a complete local path.")
    try:
        workspace = root.resolve()
        resolved = (source if source.is_absolute() else workspace / source).resolve()
    except (OSError, ValueError, RuntimeError) as error:
        raise ConfigurationError(f"The {label} local path cannot be resolved.") from error
    if str(resolved).startswith(("\\\\", "//")):
        raise ConfigurationError(f"The {label} cannot use a network or device path.")
    if not source.is_absolute() and not resolved.is_relative_to(workspace):
        raise ConfigurationError(f"A relative {label} must stay inside the workspace.")
    return resolved
