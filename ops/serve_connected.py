"""Explicit foreground launcher for the FULL-only connected persona UI.

This command does not install policies, configure services, start a model, or
claim runtime acceptance. Both the CLI acknowledgement and the existing UI
opt-in environment flag are required. The application retains its own source,
provenance, least-privilege and runtime startup checks.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from .serve import run_foreground
from typing import Mapping, Sequence


_MAX_BINDINGS_BYTES = 1_048_576
_BINDING_FIELDS = frozenset({
    "admin_login_role", "admin_password_environment_variable", "sales_division_name",
    "fixture_hash_path", "installed_policy_state_sha256", "template_contract",
    "model_service", "parser_approval",
})
_REQUIRED_SOURCES = (
    "app.py", "STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html", "schema.sql",
    "policy/access_matrix.yaml", "semantic/catalog.yaml",
    "src/inference/prompt_template.txt", "fixture_manifest.json",
    "fixture_pg_dump.sql", "STARK_T2SQL FRD 1.8.txt",
)
_DEPENDENCIES = ("streamlit", "psycopg2", "yaml", "sqlglot")


class ConnectedLaunchError(ValueError):
    """A local prerequisite is absent; messages never include private values."""


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    command: tuple[str, ...]
    root: Path
    environment: Mapping[str, str] = field(repr=False)


def command(root: Path, port: int = 8502) -> tuple[str, ...]:
    """Construct a foreground command with fixed numeric-loopback binding."""
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ConnectedLaunchError("Use an unprivileged local port from 1024 to 65535.")
    return (
        sys.executable, "-m", "streamlit", "run", str(Path(root) / "app.py"),
        "--server.address=127.0.0.1", f"--server.port={port}",
        "--server.headless=true", "--browser.gatherUsageStats=false",
        "--server.enableCORS=true", "--server.enableXsrfProtection=true",
        "--server.enableStaticServing=false",
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConnectedLaunchError("The private binding JSON has duplicate fields.")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ConnectedLaunchError("The private binding JSON contains a non-finite value.")


def _private_bindings(path: Path, root: Path) -> Path:
    """Check only local bytes/shape; never compose a runtime or open a socket."""
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ConnectedLaunchError("Use an absolute local private binding path.")
    try:
        source = path.resolve(strict=True)
        if str(source).startswith(("\\\\", "//")) or any(":" in part for part in source.parts[1:]):
            raise ConnectedLaunchError("Use an ordinary local private binding file.")
        if source.is_relative_to(root) or any(part.casefold() == ".git" for part in source.parts):
            raise ConnectedLaunchError("Keep private runtime bindings outside the repository and Git metadata.")
        if source.suffix.casefold() != ".json" or not source.is_file():
            raise ConnectedLaunchError("A private runtime binding JSON file is required.")
        with source.open("rb") as stream:
            raw = stream.read(_MAX_BINDINGS_BYTES + 1)
        if len(raw) > _MAX_BINDINGS_BYTES:
            raise ConnectedLaunchError("The private runtime binding JSON exceeds its byte bound.")
        payload = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except ConnectedLaunchError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise ConnectedLaunchError("The private runtime binding JSON is unavailable or invalid.") from None
    if type(payload) is not dict or set(payload) != _BINDING_FIELDS:
        raise ConnectedLaunchError("The private runtime binding record has missing or unexpected fields.")
    return source


def build_launch(
    root: Path,
    runtime_bindings: Path,
    *,
    port: int = 8502,
    connected_acknowledged: bool = False,
    environment: Mapping[str, str] | None = None,
) -> LaunchPlan:
    """Prepare a launch using existing files/dependencies, without runtime I/O.

    This preflight is deliberately not evidence that nested declarations are
    approved or that PostgreSQL/model services work. The application's runtime
    loader must independently validate them before providing connected answers.
    """
    values = dict(os.environ if environment is None else environment)
    if connected_acknowledged is not True or values.get("STARK_ENABLE_CONNECTED_UI") != "1":
        raise ConnectedLaunchError(
            "Connected launch requires --enable-connected-ui and STARK_ENABLE_CONNECTED_UI=1."
        )
    command(root, port)  # Reject an invalid port before reading private inputs.
    try:
        project = Path(root).resolve(strict=True)
        if any(not (project / name).is_file() for name in _REQUIRED_SOURCES):
            raise ConnectedLaunchError("A required application source or fixture artifact is unavailable.")
    except OSError:
        raise ConnectedLaunchError("The application workspace is unavailable.") from None
    source = _private_bindings(Path(runtime_bindings), project)
    try:
        if any(importlib.util.find_spec(name) is None for name in _DEPENDENCIES):
            raise ConnectedLaunchError("A required Python runtime dependency is unavailable; nothing was installed.")
    except (ImportError, ValueError, AttributeError):
        raise ConnectedLaunchError("A required Python runtime dependency is unavailable; nothing was installed.") from None
    values["STARK_RUNTIME_BINDINGS_PATH"] = str(source)
    values["PYTHONPATH"] = str(project / "src") + os.pathsep + str(project)
    values["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    # No flag is manufactured to activate connected execution. The caller's
    # exact STARK_ENABLE_CONNECTED_UI=1 is retained after the explicit checks.
    return LaunchPlan(command(project, port), project, values)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--runtime-bindings", type=Path, required=True)
    parser.add_argument("--enable-connected-ui", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = build_launch(
            Path(__file__).resolve().parents[1], args.runtime_bindings,
            port=args.port, connected_acknowledged=args.enable_connected_ui,
        )
    except ConnectedLaunchError as exc:
        print(f"Connected UI NOT STARTED: {exc}", file=sys.stderr)
        return 2
    print(
        f"Foreground connected UI: http://127.0.0.1:{args.port}. "
        "Identity is simulated. Runtime acceptance remains to be verified.",
        flush=True,
    )
    try:
        # Inherit foreground console, standard streams and Ctrl+C behavior.
        # No shell, detached process, service, browser, model or database setup.
        return run_foreground(plan.command, cwd=plan.root, env=dict(plan.environment), shell=False)
    except KeyboardInterrupt:
        return 130
    except OSError:
        print("Connected UI NOT STARTED: The foreground process could not be created.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
