"""Offline, sanitized diagnostics for the connected STARK runtime prerequisites.

This command reads explicit local source declarations only. It never opens a
service connection, imports an operator composition, starts a process, creates
configuration or approval records, changes credentials, or enables execution.
An OK declaration is not independently verified owner approval or live evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, fields
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    code: str
    status: str
    action: str


@dataclass(frozen=True, slots=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]
    live_acceptance: str = "NOT_RUN"
    production_promotion: str = "NOT_APPROVED"

    @property
    def offline_prerequisites(self) -> str:
        return "BLOCKED" if any(check.status != "OK" for check in self.checks) else "VALID"

    def to_json(self) -> str:
        return json.dumps({
            "offline_prerequisites": self.offline_prerequisites,
            "live_acceptance": self.live_acceptance,
            "production_promotion": self.production_promotion,
            "checks": [asdict(check) for check in self.checks],
        }, sort_keys=True, allow_nan=False)


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate declaration key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("Nonfinite declaration value")


def _test_only(reference: str) -> bool:
    normalized = reference.casefold().replace("_", " ").replace("-", " ")
    return "test only" in " ".join(normalized.split())


def inspect_runtime(
    *, root: str | Path | None = None, environment: Mapping[str, str] | None = None,
    verify_model_hash: bool = False,
) -> PreflightReport:
    """Inspect local prerequisites without probing the model, UI or database.

    Environment names and fixed diagnostic codes are public. Their values,
    paths, database names, login names, private record contents and exceptions
    never enter the report. Full GGUF hashing is explicitly opt-in because it
    may read several GiB. None of these checks authenticates review metadata.
    """
    values = dict(os.environ if environment is None else environment)
    project_root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]
    checks: list[PreflightCheck] = []

    def record(code: str, status: str, action: str) -> None:
        checks.append(PreflightCheck(code, status, action))

    for distribution in ("PyYAML", "sqlglot", "psycopg2-binary", "streamlit", "pandas"):
        try:
            version(distribution)
        except PackageNotFoundError:
            record("DEPENDENCY_" + distribution.upper().replace("-", "_"), "MISSING",
                   "Install the reviewed " + distribution + " dependency in the chosen environment; installation is separate.")
        else:
            record("DEPENDENCY_" + distribution.upper().replace("-", "_"), "OK",
                   distribution + " package metadata is present; this is not service verification.")
    if any(check.status == "MISSING" for check in checks):
        # Core source imports depend on these libraries. Report missing
        # packages before importing them rather than leaking an import stack.
        return PreflightReport(tuple(checks))

    # Imports are source-only. In particular do not instantiate the inference
    # client or call compose_persona_runtime/load_persona_runtime here.
    from stark_t2sql.config import load_config
    from stark_t2sql.db.persona import fixture_digest
    from stark_t2sql.inference.client import LocalModelServiceContract
    from stark_t2sql.inference.template import ReviewedTemplateContract, load_template
    from stark_t2sql.pipeline.orchestrator import RuntimeSourceInputs, load_runtime_source_inputs
    from stark_t2sql.security.validator import ParserReviewApproval
    from stark_t2sql.utils.fingerprints import sha256_file
    from stark_t2sql.utils.local_sources import resolve_runtime_path

    try:
        config = load_config(root=project_root, environment=values)
    except Exception:
        record("CONFIGURATION_INVALID", "INVALID",
               "Check numeric loopback STARK_PG_HOST/PORT and STARK_LLAMACPP_HOST/PORT, runtime limits, resource integers and explicit local paths.")
        return PreflightReport(tuple(checks))
    record("CONFIGURATION_VALID", "OK", "Static endpoint and limit declarations are valid; listeners and installed PostgreSQL major version are NOT verified.")

    sources = (
        (config.paths.approved_frd, "FRD", "approved FRD"),
        (config.paths.schema, "SCHEMA", "frozen schema.sql"),
        (config.paths.policy_matrix, "POLICY", "policy/access_matrix.yaml"),
        (config.paths.semantic_catalog, "CATALOG", "semantic/catalog.yaml"),
        (config.paths.prompt_template, "TEMPLATE", "immutable SQLCoder prompt template"),
        (config.paths.fixture_dump, "FIXTURE_DUMP", "frozen fixture dump"),
        (config.paths.fixture_manifest, "FIXTURE_MANIFEST", "frozen fixture manifest"),
        (project_root / "STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html", "VISUAL_BASELINE", "E0 visual specification"),
    )
    for path, code, label in sources:
        try:
            inside = path.resolve().is_relative_to(project_root)
            exists = inside and path.is_file()
        except (OSError, ValueError):
            inside, exists = False, False
        if not inside:
            record(code + "_OUTSIDE_WORKSPACE", "INVALID", "Keep the " + label + " source inside the reviewed project workspace.")
        elif not exists:
            record(code + "_MISSING", "MISSING", "Restore the reviewed " + label + " source; do not fabricate it.")
        else:
            record(code + "_PRESENT", "OK", "The " + label + " source is present; presence is not approval or live fidelity.")

    runtime_paths: dict[str, Path] = {}
    for path, code, setting in (
        (config.paths.model_file, "MODEL_FILE", "STARK_GGUF_PATH"),
        (config.resource_budgets.measurement_source, "MEASUREMENTS", "STARK_RESOURCE_MEASUREMENTS_PATH"),
    ):
        if path is None:
            record(code + "_MISSING", "MISSING", "Set " + setting + " to the actual reviewed local source.")
            continue
        try:
            resolved = resolve_runtime_path(path, root=project_root, label="offline prerequisite")
            exists = resolved.is_file()
        except Exception:
            record(code + "_INVALID", "INVALID", "Use an explicit local source; UNC, device, URI and escaping relative paths are not allowed.")
            continue
        if not exists:
            record(code + "_MISSING", "MISSING", "The configured " + setting + " file is unavailable; supply the real source.")
        else:
            runtime_paths[code] = resolved
            record(code + "_PRESENT", "OK", "The explicit local source exists; its operational provenance remains independently reviewed.")

    for name, value in (
        ("STARK_DATABASE_WORK_MEM_KIB", config.resource_budgets.database_work_mem_kib),
        ("STARK_DATABASE_TEMP_FILE_LIMIT_KIB", config.resource_budgets.database_temp_file_limit_kib),
        ("STARK_MODEL_MEMORY_LIMIT_MIB", config.resource_budgets.model_memory_limit_mib),
    ):
        record("BUDGET_" + name, "MISSING" if value is None else "OK",
               "Supply an actually measured and reviewed " + name + "; a configured number does not establish enforcement.")

    for name in ("STARK_PG_DATABASE", "STARK_PAYROLL_PASSWORD", "STARK_HR_PASSWORD", "STARK_SALES_PASSWORD"):
        record("ENV_" + name, "OK" if values.get(name) else "MISSING", "Set " + name + " privately in the runtime environment; do not commit its value.")
    if all(values.get(name) for name in ("STARK_PG_DATABASE", "STARK_PAYROLL_PASSWORD", "STARK_HR_PASSWORD", "STARK_SALES_PASSWORD")):
        try:
            for alias in config.database_connections:
                alias.load_credentials(values)
        except Exception:
            record("DATABASE_CREDENTIAL_DECLARATION_INVALID", "INVALID", "Use a plain database name and private per-login password variables; no DSN or control characters.")

    supplied = values.get("STARK_RUNTIME_BINDINGS_PATH")
    if not supplied:
        record("RUNTIME_BINDINGS_MISSING", "MISSING", "Set STARK_RUNTIME_BINDINGS_PATH to the actual private reviewed runtime binding JSON; no test-fixture fallback is used.")
        return PreflightReport(tuple(checks))
    try:
        binding_path = resolve_runtime_path(Path(supplied), root=project_root, label="runtime bindings")
        with binding_path.open("rb") as stream:
            payload = stream.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("Declaration exceeds bound")
        raw = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=_strict_object, parse_constant=_reject_constant)
        if type(raw) is not dict or set(raw) != {field.name for field in fields(RuntimeSourceInputs)}:
            raise ValueError("Declaration fields mismatch")
    except FileNotFoundError:
        record("RUNTIME_BINDINGS_MISSING", "MISSING", "The configured STARK_RUNTIME_BINDINGS_PATH file is unavailable; supply the real reviewed record.")
        return PreflightReport(tuple(checks))
    except Exception:
        record("RUNTIME_BINDINGS_INVALID", "INVALID", "Check explicit local path, bounded UTF-8 object JSON, exact runtime fields, duplicate keys and nonfinite values; private contents are withheld.")
        return PreflightReport(tuple(checks))

    nested_valid = True
    for key, constructor, code, action in (
        ("template_contract", ReviewedTemplateContract, "TEMPLATE_BINDING_INVALID", "Check immutable template SHA, exact model-card markers, approved as-of prefix and recorded source reference."),
        ("model_service", LocalModelServiceContract, "MODEL_BINDING_INVALID", "Supply actual GGUF/build/launcher and independently reviewed beam, post-update weight, enforced memory, one-slot and cache declarations."),
        ("parser_approval", ParserReviewApproval, "PARSER_BINDING_INVALID", "Supply the genuinely reviewed parser version, validator/function revisions and explicit tested node/function sets."),
    ):
        try:
            declaration = raw[key]
            if type(declaration) is not dict or set(declaration) != {field.name for field in fields(constructor)}:
                raise ValueError("Nested fields mismatch")
            declaration = dict(declaration)
            if key == "parser_approval":
                for selected in ("approved_node_shapes", "approved_function_rule_ids"):
                    if type(declaration[selected]) is not list or any(type(item) is not str for item in declaration[selected]):
                        raise ValueError("Expected explicit representation lists")
                    declaration[selected] = frozenset(declaration[selected])
            constructor(**declaration)
        except Exception:
            nested_valid = False
            record(code, "INVALID", action)
    if not nested_valid:
        return PreflightReport(tuple(checks))

    try:
        inputs = load_runtime_source_inputs(binding_path, root=project_root)
    except Exception:
        record("RUNTIME_BINDINGS_INVALID", "INVALID", "Check exact runtime fields, private administrative variable name, fixture digest-key path and installed policy-state SHA; declarations do not install policy.")
        return PreflightReport(tuple(checks))
    record("RUNTIME_BINDINGS_DECLARED", "OK", "Typed source declarations are structurally valid; human approval, installation and running-service claims remain unverified.")
    record("ADMIN_PASSWORD_ENVIRONMENT", "OK" if values.get(inputs.admin_password_environment_variable) else "MISSING",
           "Set the private administrative password environment variable named by the binding; it is used only for trusted startup metadata.")

    if _test_only(inputs.parser_approval.review_reference) or binding_path.is_relative_to(project_root / "tests"):
        record("PARSER_TEST_ONLY", "INVALID", "A TEST_ONLY profile or tests-directory binding cannot serve as production approval; obtain the genuine independent parser review.")
    else:
        record("PARSER_DECLARATION_PRESENT", "OK", "Parser review metadata is declared; this tool does not authenticate that review.")
    try:
        installed = version("sqlglot")
    except PackageNotFoundError:
        installed = None
    if installed != inputs.parser_approval.sqlglot_version:
        record("PARSER_VERSION_MISMATCH", "INVALID", "The installed sqlglot release must exactly match the genuine reviewed parser profile; do not broaden approvals to suppress failures.")
    else:
        record("PARSER_VERSION_MATCH", "OK", "Installed parser package version matches the declared profile; no SQL has been parsed or executed by this check.")

    try:
        load_template(config.paths.prompt_template, contract=inputs.template_contract)
    except Exception:
        record("TEMPLATE_INTEGRITY_INVALID", "INVALID", "Check actual immutable prompt bytes against the reviewed model-card contract; do not regenerate or rewrite the template.")
    else:
        record("TEMPLATE_INTEGRITY_VALID", "OK", "Immutable prompt bytes match the declared template contract; no inference was performed.")
    try:
        fixture_digest(config.paths, inputs.fixture_hash_path)
    except Exception:
        record("FIXTURE_INTEGRITY_INVALID", "INVALID", "Check the actual frozen dump, manifest digest field and declared fixture_hash_path; this tool never restores data.")
    else:
        record("FIXTURE_INTEGRITY_VALID", "OK", "Frozen dump bytes match the explicit manifest field; installed database row fidelity is NOT verified.")
    if verify_model_hash and "MODEL_FILE" in runtime_paths:
        try:
            matches = sha256_file(runtime_paths["MODEL_FILE"]) == inputs.model_service.model_sha256
        except Exception:
            matches = False
        record("MODEL_INTEGRITY_VALID" if matches else "MODEL_INTEGRITY_INVALID", "OK" if matches else "INVALID",
               "Compare the actual local GGUF SHA with the independently reviewed model-source record; a hash is not provenance or owner approval.")
    return PreflightReport(tuple(checks))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Project workspace; no files or services are created.")
    parser.add_argument("--json", action="store_true", help="Emit sanitized machine-readable diagnostics.")
    parser.add_argument("--verify-model-hash", action="store_true", help="Read the full configured GGUF to verify its SHA-256; no inference.")
    args = parser.parse_args(argv)
    # Source-layout execution works without pip installation or environment edits.
    source = Path(__file__).resolve().parents[1] / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    report = inspect_runtime(root=args.root, verify_model_hash=args.verify_model_hash)
    if args.json:
        print(report.to_json())
    else:
        print("Offline prerequisites: " + report.offline_prerequisites)
        for check in report.checks:
            print(f"{check.status} {check.code}: {check.action}")
        print("LIVE_ACCEPTANCE_NOT_EXECUTED; PRODUCTION_PROMOTION_NOT_APPROVED")
    return 0 if report.offline_prerequisites == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
