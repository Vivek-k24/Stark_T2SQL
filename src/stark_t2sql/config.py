"""Static defaults and explicit runtime configuration for later prompt owners.

Loading configuration creates no files, services, connections or log records.
Resource budgets remain unavailable until supplied from future measurements.
The approved baseline is the supplied STARK-TTSQL-FRD-1.8 source document.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Mapping

from .errors import ConfigurationError, MissingDependencyError, SourceReadError
from .utils.local_only import (
    LoopbackEndpoint,
    require_allowed_host_port,
    require_allowed_url,
)


FIXTURE_AS_OF_DATE = date(2026, 10, 12)
FRD_DOCUMENT_ID = "STARK-TTSQL-FRD-1.8"
APPROVED_FRD_FILENAME = "STARK_T2SQL FRD 1.8.txt"


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Paths to sources and future artifacts; declaring a path creates nothing."""

    root: Path
    approved_frd: Path
    schema: Path
    policy_matrix: Path
    semantic_catalog: Path
    prompt_template: Path
    events_log: Path
    evaluation_log_directory: Path
    fixture_dump: Path
    fixture_manifest: Path
    model_file: Path | None = None

    @classmethod
    def from_root(
        cls,
        root: str | Path,
        *,
        model_file: Path | None = None,
        approved_frd_file: Path | None = None,
    ) -> ProjectPaths:
        project_root = Path(root).resolve()
        frd_file = approved_frd_file if approved_frd_file is not None else Path(APPROVED_FRD_FILENAME)
        if not frd_file.is_absolute():
            frd_file = project_root / frd_file
        return cls(
            root=project_root,
            # The supplied filename differs from Prompt 1; its document ID is the baseline.
            approved_frd=frd_file,
            schema=project_root / "schema.sql",
            policy_matrix=project_root / "policy" / "access_matrix.yaml",
            semantic_catalog=project_root / "semantic" / "catalog.yaml",
            # Prompt 4 names this artifact separately from its Python package.
            prompt_template=project_root / "src" / "inference" / "prompt_template.txt",
            events_log=project_root / "logs" / "events.jsonl",
            evaluation_log_directory=project_root / "logs" / "evaluation",
            fixture_dump=project_root / "fixture_pg_dump.sql",
            fixture_manifest=project_root / "fixture_manifest.json",
            model_file=model_file,
        )


def require_source_file(path: Path | None, *, label: str) -> Path:
    """Future readers must require real input files instead of fabricating them."""
    if path is None:
        raise MissingDependencyError(f"No local path supplied for {label}.")
    try:
        exists = path.is_file()
    except OSError as exc:
        raise SourceReadError(f"Cannot inspect local source {label}: {path}") from exc
    if not exists:
        raise MissingDependencyError(f"Required local source is absent: {label}: {path}")
    return path


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    """Initial settings only; a row cap is not a query-cost or memory budget."""

    generation_timeout_seconds: float = 120.0
    statement_timeout_seconds: float = 15.0
    output_row_cap: int = 1000

    def __post_init__(self) -> None:
        for name in ("generation_timeout_seconds", "statement_timeout_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ConfigurationError(f"{name} must be finite and positive.")
        if type(self.output_row_cap) is not int or self.output_row_cap <= 0:
            raise ConfigurationError("output_row_cap must be a positive integer.")


@dataclass(frozen=True, slots=True)
class ResourceBudgets:
    """Unmeasured budgets are None, never speculative operational defaults.

    Prompt 2 owns database enforcement and Prompt 4 owns model resource controls.
    A supplied measurement path is a dependency, not proof of adequate limits.
    """

    database_work_mem_kib: int | None = None
    database_temp_file_limit_kib: int | None = None
    model_memory_limit_mib: int | None = None
    measurement_source: Path | None = None

    def __post_init__(self) -> None:
        for name in (
            "database_work_mem_kib",
            "database_temp_file_limit_kib",
            "model_memory_limit_mib",
        ):
            value = getattr(self, name)
            # A zero temporary-file allowance is meaningful; memory must be > 0.
            minimum = 0 if name == "database_temp_file_limit_kib" else 1
            if value is not None and (type(value) is not int or value < minimum):
                raise ConfigurationError(f"{name} must be an integer >= {minimum}.")

    def require_database_budget_inputs(self) -> ResourceBudgets:
        """Require inputs; later owners must establish provenance and enforcement."""
        if self.database_work_mem_kib is None or self.database_temp_file_limit_kib is None:
            raise MissingDependencyError("Measured database resource budgets are unavailable.")
        require_source_file(self.measurement_source, label="resource budget measurements")
        return self


@dataclass(frozen=True, slots=True)
class IsolationControls:
    """Harness opt-in is configuration, never an execution capability.

    Prompt 2 must establish disposable, nonprivileged SELECT-only isolation before
    granting a harness capability. Persona-facing requests always use FULL.
    """

    evaluation_enabled: bool = False
    evaluation_connection_alias: str | None = None
    max_concurrent_requests: int = field(default=1, init=False)
    require_disposable_fixture_clone: bool = field(default=True, init=False)
    require_select_only_candidate_login: bool = field(default=True, init=False)
    allow_administrative_candidate_execution: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.evaluation_enabled) is not bool:
            raise ConfigurationError("evaluation_enabled must be a boolean.")
        if self.evaluation_enabled and not self.evaluation_connection_alias:
            raise MissingDependencyError("An isolated evaluation connection alias is required.")


@dataclass(frozen=True, slots=True)
class DatabaseCredentials:
    """Runtime-only secrets; do not serialize this object into outcomes or traces."""

    host: str
    port: int
    database: str
    login_role: str
    password: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DatabaseConnectionAlias:
    """A connection alias for one login role, without a secret in tracked source."""

    alias: str
    login_role: str
    host: str
    port: int
    database_environment_variable: str
    password_environment_variable: str

    def __post_init__(self) -> None:
        # Canonical numeric hosts keep future clients from resolving DNS names.
        endpoint = LoopbackEndpoint("postgresql", self.host, self.port)
        object.__setattr__(self, "host", endpoint.host)
        object.__setattr__(self, "port", endpoint.port)

    def load_credentials(self, environment: Mapping[str, str] | None = None) -> DatabaseCredentials:
        """Read credentials later; connection pools belong to Prompt 2."""
        values = os.environ if environment is None else environment
        database = values.get(self.database_environment_variable, "")
        password = values.get(self.password_environment_variable, "")
        if not database.strip() or not password:
            raise MissingDependencyError(f"Runtime credentials are unavailable for alias {self.alias}.")
        if (
            "=" in database
            or "://" in database
            or any(ord(character) < 32 or ord(character) == 127 for character in database)
        ):
            # Keep driver connection-string expansion out of the database-name field.
            raise ConfigurationError("The database setting must be a name, not a connection string.")
        return DatabaseCredentials(
            host=self.host,
            port=self.port,
            database=database,
            login_role=self.login_role,
            password=password,
        )


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Connection and artifact declarations consumed by later runtime modules."""

    paths: ProjectPaths
    limits: RuntimeLimits
    resource_budgets: ResourceBudgets
    isolation: IsolationControls
    llama_cpp_url: str
    allowed_runtime_endpoints: tuple[LoopbackEndpoint, ...]
    database_connections: tuple[DatabaseConnectionAlias, ...]
    fixture_as_of_date: date = field(default=FIXTURE_AS_OF_DATE, init=False)

    def __post_init__(self) -> None:
        if not self.allowed_runtime_endpoints:
            raise ConfigurationError("Explicit runtime endpoints are required.")
        canonical_model_url = require_allowed_url(
            self.llama_cpp_url, allowed_endpoints=self.allowed_runtime_endpoints
        )
        object.__setattr__(self, "llama_cpp_url", canonical_model_url)
        aliases = [connection.alias for connection in self.database_connections]
        if len(set(aliases)) != len(aliases):
            raise ConfigurationError("Database connection aliases must be unique.")
        for connection in self.database_connections:
            require_allowed_host_port(
                connection.host,
                connection.port,
                scheme="postgresql",
                allowed_endpoints=self.allowed_runtime_endpoints,
            )

    def database_alias(self, alias: str) -> DatabaseConnectionAlias:
        for connection in self.database_connections:
            if connection.alias == alias:
                return connection
        raise ConfigurationError(f"Unknown database connection alias: {alias}")


def _integer_setting(values: Mapping[str, str], name: str, *, default: int | None) -> int | None:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        # Do not include raw environment values, which could contain secrets.
        raise ConfigurationError(f"{name} must be an integer.") from exc


def _seconds_setting(values: Mapping[str, str], name: str, *, default: float) -> float:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be a number.") from exc


def load_config(
    *, root: str | Path | None = None, environment: Mapping[str, str] | None = None
) -> AppConfig:
    """Read explicit settings later; no dependency files are opened by this loader.

    STARK_LLAMACPP_HOST/PORT and STARK_PG_HOST/PORT declare exact local endpoints.
    External hosts are rejected even when explicitly present in the environment.
    No DSN is accepted here; passwords remain in per-login environment variables.
    """
    values = os.environ if environment is None else environment
    project_root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    frd_setting = values.get("STARK_FRD_PATH")
    frd_path = Path(frd_setting) if frd_setting else None
    model_setting = values.get("STARK_GGUF_PATH")
    model_path = Path(model_setting) if model_setting else None
    if model_path is not None and not model_path.is_absolute():
        model_path = project_root / model_path
    measurement_setting = values.get("STARK_RESOURCE_MEASUREMENTS_PATH")
    measurement_path = Path(measurement_setting) if measurement_setting else None
    if measurement_path is not None and not measurement_path.is_absolute():
        measurement_path = project_root / measurement_path

    # These ports are initial configuration assumptions, not discovered services.
    model_port = _integer_setting(values, "STARK_LLAMACPP_PORT", default=8080)
    database_port = _integer_setting(values, "STARK_PG_PORT", default=5432)
    if model_port is None or database_port is None:
        raise ConfigurationError("Runtime endpoint ports must be supplied.")
    model_endpoint = LoopbackEndpoint("http", values.get("STARK_LLAMACPP_HOST", "127.0.0.1"), model_port)
    database_endpoint = LoopbackEndpoint(
        "postgresql", values.get("STARK_PG_HOST", "127.0.0.1"), database_port
    )
    model_host = f"[{model_endpoint.host}]" if ":" in model_endpoint.host else model_endpoint.host
    model_url = f"http://{model_host}:{model_endpoint.port}"
    endpoints = (model_endpoint, database_endpoint)

    row_cap = _integer_setting(values, "STARK_OUTPUT_ROW_CAP", default=1000)
    if row_cap is None:
        raise ConfigurationError("The output row cap must be supplied.")
    connection_declarations = (
        ("payroll", "stark_payroll_login", "STARK_PAYROLL_PASSWORD"),
        ("hr", "stark_hr_login", "STARK_HR_PASSWORD"),
        ("sales", "stark_sales_login", "STARK_SALES_PASSWORD"),
    )
    return AppConfig(
        paths=ProjectPaths.from_root(project_root, model_file=model_path, approved_frd_file=frd_path),
        limits=RuntimeLimits(
            generation_timeout_seconds=_seconds_setting(values, "STARK_GENERATION_TIMEOUT_SECONDS", default=120.0),
            statement_timeout_seconds=_seconds_setting(values, "STARK_STATEMENT_TIMEOUT_SECONDS", default=15.0),
            output_row_cap=row_cap,
        ),
        resource_budgets=ResourceBudgets(
            database_work_mem_kib=_integer_setting(values, "STARK_DATABASE_WORK_MEM_KIB", default=None),
            database_temp_file_limit_kib=_integer_setting(values, "STARK_DATABASE_TEMP_FILE_LIMIT_KIB", default=None),
            model_memory_limit_mib=_integer_setting(values, "STARK_MODEL_MEMORY_LIMIT_MIB", default=None),
            measurement_source=measurement_path,
        ),
        # Harness activation requires separately authored isolation configuration.
        isolation=IsolationControls(),
        llama_cpp_url=require_allowed_url(model_url, allowed_endpoints=endpoints),
        allowed_runtime_endpoints=endpoints,
        database_connections=tuple(
            DatabaseConnectionAlias(
                alias=alias,
                login_role=login_role,
                host=database_endpoint.host,
                port=database_endpoint.port,
                database_environment_variable="STARK_PG_DATABASE",
                password_environment_variable=password_variable,
            )
            for alias, login_role, password_variable in connection_declarations
        ),
    )
