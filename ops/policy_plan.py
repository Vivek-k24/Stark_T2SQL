"""Offline security-policy change planning; never connects or installs SQL.

Run ``python -m ops.policy_plan --help`` for explicit inputs. Output is metadata
only. Compiler equality is not measurement review, owner approval, PostgreSQL
syntax validation, installation, or observed authorization behavior.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping

from stark_t2sql.policy.compiler import CompileSettings, compile_policy
from stark_t2sql.policy.loader import authorization_specs, load_policy, require_policy_schema
from stark_t2sql.policy.privileges import managed_role_names
from stark_t2sql.utils.local_only import require_loopback_host


class PlanInputError(ValueError):
    """Fixed, non-sensitive error codes; never echo paths, SQL or credentials."""


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,62}\Z")
_STRUCTURAL_ONLY = b"STARK_POLICY_OFFLINE_STRUCTURE_ONLY_NOT_RESOURCE_MEASUREMENT"
_LIMIT = 1024 * 1024


def _name(value: object) -> str:
    if type(value) is not str or not _NAME.fullmatch(value):
        raise PlanInputError("INVALID_NON_SECRET_IDENTIFIER")
    return value


def _read(path: Path, *, maximum: int = _LIMIT) -> bytes:
    try:
        with path.open("rb") as stream:
            result = stream.read(maximum + 1)
    except OSError:
        raise PlanInputError("INPUT_UNAVAILABLE") from None
    if len(result) > maximum:
        raise PlanInputError("INPUT_SIZE_LIMIT")
    return result


def _digest(path: Path) -> str:
    value = sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_LIMIT), b""):
                value.update(chunk)
    except OSError:
        raise PlanInputError("INPUT_UNAVAILABLE") from None
    return value.hexdigest()


def _json(payload: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PlanInputError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    try:
        result = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(PlanInputError("INVALID_JSON")))
    except (ValueError, UnicodeError):
        raise PlanInputError("INVALID_JSON") from None
    if type(result) is not dict:
        raise PlanInputError("JSON_OBJECT_REQUIRED")
    return result


def source_columns(schema: bytes, *, expected_schema: str) -> dict[str, tuple[str, ...]]:
    """Parse frozen DDL locally, independently of candidate SQL permission review."""
    import sqlglot
    from sqlglot import exp

    try:
        statements = sqlglot.parse(schema.decode("utf-8-sig"), read="postgres")
        result = {}
        for item in statements:
            if not isinstance(item, exp.Create) or item.kind != "TABLE":
                continue
            relation = item.this.this
            if relation.db != expected_schema or relation.catalog or relation.name in result:
                raise PlanInputError("UNEXPECTED_SCHEMA_TABLE")
            result[relation.name] = tuple(column.name for column in item.this.expressions
                                          if isinstance(column, exp.ColumnDef))
        if not result:
            raise PlanInputError("SCHEMA_TABLES_UNAVAILABLE")
        return result
    except (UnicodeError, sqlglot.errors.ParseError, AttributeError):
        raise PlanInputError("SCHEMA_PARSE_FAILED") from None


def _secret_scan(payload: bytes) -> bool:
    """Conservative literal scan, not a guarantee that arbitrary input is public."""
    text = payload.decode("utf-8-sig", errors="replace")
    patterns = (
        r"\bPASSWORD\s+(?!NULL\b)(?:E)?'",
        r"\b(?:password|passwd|pwd|token|secret|api[_-]?key)\s*(?:=|:)\s*[^\s,;]+",
        r"\b(?:postgres(?:ql)?|https?)://[^\s/:]+:[^\s/@]+@",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def compare_catalog(expected: Mapping, observation: Mapping | None) -> dict:
    """Compare a separately obtained, non-secret metadata inventory, never query.

    This intentionally small contract checks names and FORCE RLS inventory only.
    ACLs, policy predicates, membership options and runtime behavior need separate
    full catalog review. A supplied file is not authenticated live evidence.
    """
    if observation is None:
        return {"status": "NOT_PROVIDED", "live_verification": "NOT_EXECUTED"}
    required = {"schema_version", "target", "roles", "public_tables", "rls", "policies"}
    if set(observation) != required or observation["schema_version"] != "stark-policy-catalog-v1":
        raise PlanInputError("INVALID_CATALOG_METADATA")
    target = observation["target"]
    if type(target) is not dict or set(target) != {"host", "port", "database", "server_major"}:
        raise PlanInputError("INVALID_CATALOG_TARGET")
    if target != expected["target"]:
        raise PlanInputError("CATALOG_TARGET_MISMATCH")
    for key in ("roles", "public_tables", "policies"):
        values = observation[key]
        if type(values) is not list or any(type(value) is not str for value in values):
            raise PlanInputError("INVALID_CATALOG_METADATA")
        if len(set(values)) != len(values):
            raise PlanInputError("DUPLICATE_CATALOG_ENTRY")
        for value in values:
            _name(value)
    rls = observation["rls"]
    if type(rls) is not dict:
        raise PlanInputError("INVALID_CATALOG_RLS")
    for name, flags in rls.items():
        _name(name)
        if (type(flags) is not dict or set(flags) != {"enabled", "forced"}
                or any(type(value) is not bool for value in flags.values())):
            raise PlanInputError("INVALID_CATALOG_RLS")
    return {
        "status": "SUPPLIED_METADATA_ONLY_NOT_LIVE_ACCEPTANCE",
        "missing_managed_roles": sorted(set(expected["managed_roles"]) - set(observation["roles"])),
        "unrelated_public_tables": sorted(set(observation["public_tables"]) - set(expected["tables"])),
        "missing_fixture_tables": sorted(set(expected["tables"]) - set(observation["public_tables"])),
        "missing_policy_names": sorted(set(expected["policy_names"]) - set(observation["policies"])),
        "additional_policy_names": sorted(set(observation["policies"]) - set(expected["policy_names"])),
        "rls_enable_or_force_missing": sorted(name for name in expected["rls_tables"]
            if rls.get(name) != {"enabled": True, "forced": True}),
        "acl_predicate_membership_and_behavior_review": "STILL_REQUIRED",
    }


def build_plan(*, root: Path, draft: Path, database: str, host: str, port: int,
               server_major: int, work_mem_kib: int, temp_file_limit_kib: int,
               definer_owner: str = "stark_scope_owner", statement_timeout_ms: int = 15000,
               measurement_evidence: Path | None = None,
               catalog_observation: Mapping | None = None) -> dict:
    """Return a no-execution/no-approval report; never return raw SQL or secrets."""
    _name(database)
    _name(definer_owner)
    try:
        if type(host) is not str or host.lower() == "localhost":
            raise PlanInputError("NUMERIC_LOOPBACK_HOST_REQUIRED")
        host = require_loopback_host(host)
    except Exception:
        raise PlanInputError("NUMERIC_LOOPBACK_HOST_REQUIRED") from None
    if type(port) is not int or not 1 <= port <= 65535 or type(server_major) is not int or server_major < 1:
        raise PlanInputError("INVALID_DECLARED_TARGET")
    matrix_path = root / "policy" / "access_matrix.yaml"
    try:
        matrix = load_policy(matrix_path)
        schema_bytes = _read(root / "schema.sql")
        columns = source_columns(schema_bytes, expected_schema=matrix.schema)
        require_policy_schema(matrix, columns)
        evidence_digest = _digest(measurement_evidence) if measurement_evidence is not None else None
        # Compiler requires provenance operands. Without a supplied artifact,
        # these explicit structure-only operands are NEVER installation inputs.
        settings = CompileSettings(definer_owner, statement_timeout_ms=statement_timeout_ms,
            work_mem_kib=work_mem_kib, temp_file_limit_kib=temp_file_limit_kib,
            measurement_sha256=evidence_digest or sha256(_STRUCTURAL_ONLY).hexdigest(),
            measurement_provenance="OFFLINE_STRUCTURE_ONLY_NOT_MEASUREMENT_APPROVAL")
        compiled = compile_policy(matrix, columns, settings)
    except PlanInputError:
        raise
    except Exception:
        raise PlanInputError("POLICY_COMPILATION_FAILED") from None
    raw = _read(draft)
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeError:
        raise PlanInputError("DRAFT_ENCODING_INVALID") from None
    secret_found = _secret_scan(raw)
    matches = not secret_found and text == compiled.sql_text
    specs = authorization_specs(matrix, columns)
    policy_names = sorted({f"stark_select_{role.name}" for role in matrix.roles
                           if any(table in role.tables for table in matrix.rls_tables)})
    expected = {
        "target": {"host": host, "port": port, "database": database, "server_major": server_major},
        "managed_roles": list(managed_role_names(matrix, definer_owner)),
        "tables": list(matrix.tables), "rls_tables": list(matrix.rls_tables),
        "policy_names": policy_names,
    }
    blockers = ["OWNER_ADMINISTRATIVE_APPROVAL_REQUIRED", "ACTUAL_TARGET_AND_FIXTURE_VERIFICATION_REQUIRED",
                "MEASUREMENT_QUALITY_AND_ENFORCEMENT_UNVERIFIED", "BACKUP_AND_RESTORE_REVIEW_REQUIRED",
                "CANONICAL_GUARDED_INSTALLER_REQUIRED"]
    if not matches:
        blockers.append("DRAFT_DIFFERS_FROM_CURRENT_COMPILER")
    if secret_found:
        blockers.append("SENSITIVE_LITERAL_SCAN_REJECTED_DRAFT")
    if evidence_digest is None:
        blockers.append("RESOURCE_MEASUREMENT_ARTIFACT_NOT_SUPPLIED")
    if server_major != 16:
        blockers.append("FRD_POSTGRESQL_16_DEVIATION_REQUIRES_OWNER_DECISION")
    manifest = _json(_read(root / "fixture_manifest.json"))
    dump_digest = _digest(root / "fixture_pg_dump.sql")
    if manifest.get("fixture_dump_sha256") != dump_digest:
        raise PlanInputError("FROZEN_DUMP_MANIFEST_MISMATCH")
    comparison = compare_catalog(expected, catalog_observation)
    if comparison.get("unrelated_public_tables"):
        blockers.append("UNRELATED_PUBLIC_TABLES_WOULD_HAVE_ACLS_CHANGED")
    return {
        "schema_version": "stark-offline-policy-plan-v1", "status": "APPROVAL_REQUIRED",
        "authorization": "NOT_GRANTED", "database_changed": False,
        "live_acceptance": "NOT_EXECUTED", "declared_target": expected["target"],
        "target_identity": "DECLARED_NOT_OBSERVED_BY_THIS_TOOL",
        "sources": {"matrix_sha256": matrix.sha256, "schema_sha256": sha256(schema_bytes).hexdigest(),
                    "fixture_dump_sha256": dump_digest,
                    "fixture_manifest_sha256": _digest(root / "fixture_manifest.json")},
        "draft": {"sha256": sha256(raw).hexdigest(), "byte_count": len(raw),
                  "sensitive_literal_scan": "REJECTED" if secret_found else "NO_PATTERN_MATCH_NOT_A_GUARANTEE",
                  "newline_normalized_compiler_match": matches,
                  "statement_count": len(compiled.statements) if matches else None,
                  "outer_transaction": "ABSENT" if matches else "UNVERIFIED",
                  "enforcing_target_identity_guard": "ABSENT" if matches else "UNVERIFIED"},
        "compiler": {"statement_count": len(compiled.statements),
                     "sql_text_sha256": sha256(compiled.sql_text.encode("utf-8")).hexdigest(),
                     "baseline_eval_login": None, "comparison_only": True},
        "resources": {"work_mem_kib": work_mem_kib, "temp_file_limit_kib": temp_file_limit_kib,
                      "statement_timeout_ms": statement_timeout_ms,
                      "evidence_sha256": evidence_digest,
                      "measurement_status": "PRESENT_NOT_VERIFIED" if evidence_digest else "NOT_SUPPLIED",
                      "compiler_provenance": "STRUCTURE_ONLY_NEVER_INSTALLATION_AUTHORITY"},
        "expected_inventory": {**expected, "authorization_probe_count": len(specs),
            "login_memberships": [{"business_role": role.name, "login_role": role.login_role,
                                    "admin": False, "inherit": False, "set": True} for role in matrix.roles],
            "managed_role_attributes": [{"name": name, "login": name in {role.login_role for role in matrix.roles},
                "inherit": False, "superuser": False, "bypassrls": False, "createdb": False,
                "createrole": False, "replication": False} for name in expected["managed_roles"]],
            "select_grants": [{"business_role": role.name, "table": table,
                "columns": "*" if access.columns is None else list(access.columns),
                "row_scope": access.row_scope.value} for role in matrix.roles for table, access in role.tables.items()],
            "select_policies": [{"table": table, "name": f"stark_select_{role.name}",
                "business_role": role.name, "row_scope": role.tables[table].row_scope.value}
                for table in matrix.rls_tables for role in matrix.roles if table in role.tables],
            "policy_count": sum(table in role.tables for table in matrix.rls_tables for role in matrix.roles),
            "hr_helper": {"schema": matrix.schema, "name": "hr_bp_current_divisions",
                "argument_count": 0, "volatility": "STABLE", "security_definer": True,
                "owner": definer_owner, "search_path": ["pg_catalog", matrix.schema, "pg_temp"],
                "execute_grantees": ["app_hr_bp"], "backing_table": "hr_bp_assignments",
                "backing_columns": ["employee_id", "division_id", "effective_to"]}},
        "catalog_comparison": comparison,
        "mutations": [
            {"category": "GLOBAL_ROLES_AND_MEMBERSHIPS", "scope": "CLUSTER_GLOBAL",
             "impact": "Normalize managed role attributes; reset defaults; CASCADE-revoke all touching memberships and rebuild three approved edges."},
            {"category": "GLOBAL_AND_DATABASE_ROLE_DEFAULTS", "scope": "GLOBAL_AND_TARGET_DATABASE",
             "impact": "Global managed-role defaults can change behavior in unrelated databases; current-database overrides are also replaced."},
            {"category": "SCHEMA_WIDE_ACL_REPLACEMENT", "scope": "ALL_PUBLIC_TABLES_SEQUENCES_AND_COLUMNS",
             "impact": "PUBLIC and managed-role ACLs are revoked with CASCADE, including unrelated objects in public; restricted columns retain column-only grants."},
            {"category": "SCHEMA_AND_DATABASE_CREATE_TEMP", "scope": "TARGET_DATABASE_PUBLIC_AND_MANAGED_ROLES",
             "impact": "Revoke PUBLIC schema CREATE and database CREATE/TEMP; unrelated consumers can be affected."},
            {"category": "HR_DEFINER_FUNCTION", "scope": "TARGET_DATABASE_PUBLIC",
             "impact": "Replace zero-argument STABLE SECURITY DEFINER helper, transfer least-privilege ownership, pin trusted path, restrict EXECUTE."},
            {"category": "RLS_POLICY_REPLACEMENT", "scope": "EMPLOYEES_AND_LEAVE_BALANCES",
             "impact": "Drop all existing policies; enable and FORCE RLS; install five matrix-derived SELECT policies."},
            {"category": "BUILTIN_SET_CONFIG_EXECUTE", "scope": "TARGET_DATABASE_FUNCTION_ACL",
             "impact": "Revoke PUBLIC/managed EXECUTE and grant three logins only, after fixture restore; SQL SET remains a validator-dependent gap."},
        ],
        "installation_requirements": ["Never psql-apply the unwrapped raw draft.",
            "Use policy_apply with a freshly reproduced compiler plan, actual schema, actual measured inputs, exact database and fixture bindings, after verified restore.",
            "Obtain target-specific owner approval and verified backup/recovery plan before role, membership, ACL, function or policy changes.",
            "No reset, restore, credential change, service or security-policy change is authorized by this report.",
            "No baseline policies are included; isolated evaluation clone provisioning is a separate approved operation."],
        "blockers": blockers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--server-major", type=int, required=True)
    parser.add_argument("--definer-owner", default="stark_scope_owner")
    parser.add_argument("--statement-timeout-ms", type=int, default=15000)
    parser.add_argument("--work-mem-kib", type=int, required=True)
    parser.add_argument("--temp-file-limit-kib", type=int, required=True)
    parser.add_argument("--measurement-evidence", type=Path)
    parser.add_argument("--catalog-snapshot", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_plan(root=args.root, draft=args.draft, database=args.database,
            host=args.host, port=args.port, server_major=args.server_major,
            definer_owner=args.definer_owner, statement_timeout_ms=args.statement_timeout_ms,
            work_mem_kib=args.work_mem_kib, temp_file_limit_kib=args.temp_file_limit_kib,
            measurement_evidence=args.measurement_evidence,
            catalog_observation=_json(_read(args.catalog_snapshot)) if args.catalog_snapshot else None)
    except PlanInputError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "database_changed": False}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["draft"]["newline_normalized_compiler_match"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
