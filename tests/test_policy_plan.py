"""Offline policy planning: no database, credentials, SQL execution or approval."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from ops.policy_plan import PlanInputError, build_plan, compare_catalog, main, source_columns
from stark_t2sql.policy.compiler import CompileSettings, compile_policy
from stark_t2sql.policy.loader import load_policy


@pytest.fixture
def offline_draft(project_root, tmp_path):
    matrix = load_policy(project_root / "policy/access_matrix.yaml")
    columns = source_columns((project_root / "schema.sql").read_bytes(), expected_schema="public")
    settings = CompileSettings("stark_scope_owner", work_mem_kib=4096, temp_file_limit_kib=65536,
        measurement_sha256=sha256(b"TEST_ONLY_NOT_MEASUREMENT").hexdigest(),
        measurement_provenance="TEST_ONLY_NOT_MEASUREMENT")
    draft = tmp_path / "unit-draft.sql"
    draft.write_bytes(compile_policy(matrix, columns, settings).sql_text.replace("\n", "\r\n").encode())
    return dict(root=project_root, draft=draft, database="stark_t2sql", host="127.0.0.1",
                port=5433, server_major=17, work_mem_kib=4096, temp_file_limit_kib=65536)


def test_canonical_crlf_draft_has_exact_count_and_explicit_unapproved_state(offline_draft):
    report = build_plan(**offline_draft)
    assert report["draft"]["newline_normalized_compiler_match"] is True
    assert report["draft"]["statement_count"] == 97
    assert report["draft"]["sha256"] == sha256(offline_draft["draft"].read_bytes()).hexdigest()
    assert report["draft"]["outer_transaction"] == "ABSENT"
    assert report["draft"]["enforcing_target_identity_guard"] == "ABSENT"
    assert report["expected_inventory"]["authorization_probe_count"] == 273
    assert report["expected_inventory"]["policy_count"] == 5
    assert len(report["expected_inventory"]["managed_roles"]) == 7
    assert report["compiler"]["baseline_eval_login"] is None
    assert report["authorization"] == "NOT_GRANTED"
    assert report["database_changed"] is False and report["live_acceptance"] == "NOT_EXECUTED"
    assert report["target_identity"] == "DECLARED_NOT_OBSERVED_BY_THIS_TOOL"
    assert "FRD_POSTGRESQL_16_DEVIATION_REQUIRES_OWNER_DECISION" in report["blockers"]
    assert report["resources"]["measurement_status"] == "NOT_SUPPLIED"
    assert report["resources"]["evidence_sha256"] is None


def test_scope_includes_unrelated_acl_and_global_role_effects(offline_draft):
    report = build_plan(**offline_draft)
    changes = {item["category"]: item for item in report["mutations"]}
    assert changes["GLOBAL_ROLES_AND_MEMBERSHIPS"]["scope"] == "CLUSTER_GLOBAL"
    assert changes["GLOBAL_AND_DATABASE_ROLE_DEFAULTS"]["scope"] == "GLOBAL_AND_TARGET_DATABASE"
    assert changes["SCHEMA_WIDE_ACL_REPLACEMENT"]["scope"] == "ALL_PUBLIC_TABLES_SEQUENCES_AND_COLUMNS"
    assert changes["BUILTIN_SET_CONFIG_EXECUTE"]["scope"] == "TARGET_DATABASE_FUNCTION_ACL"
    assert "SQL SET" in changes["BUILTIN_SET_CONFIG_EXECUTE"]["impact"]
    assert any("Never psql-apply" in line for line in report["installation_requirements"])
    inventory = report["expected_inventory"]
    grants = {(item["business_role"], item["table"]): item for item in inventory["select_grants"]}
    assert grants[("app_hr_bp", "employees")]["columns"] != "*"
    assert "employee_number" not in grants[("app_hr_bp", "employees")]["columns"]
    assert grants[("app_sales_mgr", "employees")]["columns"] != "*"
    assert ("app_hr_bp", "employee_compensation") not in grants
    assert ("app_sales_mgr", "payroll_results") not in grants
    assert len(inventory["select_policies"]) == 5
    assert inventory["hr_helper"]["execute_grantees"] == ["app_hr_bp"]
    assert inventory["hr_helper"]["search_path"] == ["pg_catalog", "public", "pg_temp"]


def test_changed_or_transaction_wrapped_draft_does_not_inherit_canonical_count(offline_draft):
    draft = offline_draft["draft"]
    draft.write_bytes(b"BEGIN;\n" + draft.read_bytes() + b"COMMIT;\n")
    report = build_plan(**offline_draft)
    assert report["draft"]["newline_normalized_compiler_match"] is False
    assert report["draft"]["statement_count"] is None
    assert report["draft"]["outer_transaction"] == "UNVERIFIED"
    assert "DRAFT_DIFFERS_FROM_CURRENT_COMPILER" in report["blockers"]


@pytest.mark.parametrize("private", [
    b"ALTER ROLE unit LOGIN PASSWORD 'DO_NOT_PRINT_UNIT_SECRET';",
    b"-- password=DO_NOT_PRINT_UNIT_SECRET",
    b"-- postgresql://unit:DO_NOT_PRINT_UNIT_SECRET@127.0.0.1/db",
    b"-----BEGIN PRIVATE KEY-----\nDO_NOT_PRINT_UNIT_SECRET",
])
def test_sensitive_draft_is_rejected_without_echo(offline_draft, private):
    offline_draft["draft"].write_bytes(private)
    report = build_plan(**offline_draft)
    output = json.dumps(report)
    assert "DO_NOT_PRINT_UNIT_SECRET" not in output
    assert report["draft"]["sensitive_literal_scan"] == "REJECTED"
    assert report["draft"]["statement_count"] is None
    assert report["draft"]["newline_normalized_compiler_match"] is False


@pytest.mark.parametrize("field,value", [
    ("host", "0.0.0.0"), ("host", "localhost"), ("host", "example.com"),
    ("database", "postgresql://private:DO_NOT_PRINT_UNIT_SECRET@host/db"),
    ("database", "dbname=x password=DO_NOT_PRINT_UNIT_SECRET"), ("port", 0),
    ("server_major", True), ("definer_owner", "unsafe\nname"),
])
def test_invalid_declared_target_fails_without_echo(offline_draft, field, value):
    with pytest.raises(PlanInputError) as exc:
        build_plan(**dict(offline_draft, **{field: value}))
    assert "DO_NOT_PRINT_UNIT_SECRET" not in str(exc.value)


def test_supplied_measurement_bytes_are_hashed_never_approved_or_printed(offline_draft, tmp_path):
    artifact = tmp_path / "measurement.txt"
    artifact.write_bytes(b"TEST_ONLY_PRIVATE_OBSERVATION_NOT_A_MEASUREMENT_APPROVAL")
    report = build_plan(**offline_draft, measurement_evidence=artifact)
    assert report["resources"]["evidence_sha256"] == sha256(artifact.read_bytes()).hexdigest()
    assert report["resources"]["measurement_status"] == "PRESENT_NOT_VERIFIED"
    assert "TEST_ONLY_PRIVATE_OBSERVATION" not in json.dumps(report)
    assert "MEASUREMENT_QUALITY_AND_ENFORCEMENT_UNVERIFIED" in report["blockers"]
    assert report["authorization"] == "NOT_GRANTED"


def _catalog(expected):
    return {"schema_version": "stark-policy-catalog-v1", "target": deepcopy(expected["target"]),
            "roles": list(expected["managed_roles"]), "public_tables": list(expected["tables"]),
            "policies": list(expected["policy_names"]),
            "rls": {name: {"enabled": True, "forced": True} for name in expected["rls_tables"]}}


def test_separate_catalog_diff_reports_unrelated_objects_and_missing_rls(offline_draft):
    expected = build_plan(**offline_draft)["expected_inventory"]
    observation = _catalog(expected)
    observation["public_tables"].append("unrelated_table")
    observation["roles"].remove("stark_hr_login")
    observation["rls"]["employees"]["forced"] = False
    report = build_plan(**offline_draft, catalog_observation=observation)
    diff = report["catalog_comparison"]
    assert diff["unrelated_public_tables"] == ["unrelated_table"]
    assert diff["missing_managed_roles"] == ["stark_hr_login"]
    assert diff["rls_enable_or_force_missing"] == ["employees"]
    assert diff["acl_predicate_membership_and_behavior_review"] == "STILL_REQUIRED"
    assert "UNRELATED_PUBLIC_TABLES_WOULD_HAVE_ACLS_CHANGED" in report["blockers"]


def test_complete_supplied_inventory_remains_unapproved_and_not_live(offline_draft):
    expected = build_plan(**offline_draft)["expected_inventory"]
    report = build_plan(**offline_draft, catalog_observation=_catalog(expected))
    assert report["catalog_comparison"]["status"] == "SUPPLIED_METADATA_ONLY_NOT_LIVE_ACCEPTANCE"
    assert report["authorization"] == "NOT_GRANTED" and report["status"] == "APPROVAL_REQUIRED"


@pytest.mark.parametrize("change", ["target", "extra", "secret", "duplicate", "wrong_bool"])
def test_catalog_contract_cannot_accept_extra_private_inputs_or_wrong_target(offline_draft, change):
    expected = build_plan(**offline_draft)["expected_inventory"]
    observation = _catalog(expected)
    if change == "target": observation["target"]["port"] = 5432
    if change == "extra": observation["password"] = "DO_NOT_PRINT_UNIT_SECRET"
    if change == "secret": observation["roles"].append("password=DO_NOT_PRINT_UNIT_SECRET")
    if change == "duplicate": observation["roles"].append(observation["roles"][0])
    if change == "wrong_bool": observation["rls"]["employees"]["forced"] = 1
    with pytest.raises(PlanInputError) as exc:
        compare_catalog(expected, observation)
    assert "DO_NOT_PRINT_UNIT_SECRET" not in str(exc.value)


def test_main_emits_metadata_only_and_exposes_no_apply_option(offline_draft, capsys):
    args = ["--root", str(offline_draft["root"]), "--draft", str(offline_draft["draft"]),
            "--database", "stark_t2sql", "--port", "5433", "--server-major", "17",
            "--work-mem-kib", "4096", "--temp-file-limit-kib", "65536"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["authorization"] == "NOT_GRANTED"
    assert "regenerated_sql" not in report and "statements" not in report
    with pytest.raises(SystemExit):
        main(args + ["--execute"])


def test_offline_planning_never_connects_starts_process_or_reads_credentials(offline_draft, monkeypatch):
    import psycopg2
    from stark_t2sql.config import DatabaseConnectionAlias

    def forbidden(*args, **kwargs):
        raise AssertionError("No live operation or credential read is permitted")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(psycopg2, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(DatabaseConnectionAlias, "load_credentials", forbidden)
    module_path = Path(__file__).resolve().parents[1] / "ops/policy_plan.py"
    spec = importlib.util.spec_from_file_location("unit_policy_plan_fresh_import", module_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert module.build_plan(**offline_draft)["database_changed"] is False


def test_source_metadata_refuses_an_unexpected_schema_or_duplicate_table():
    with pytest.raises(PlanInputError):
        source_columns(b"CREATE TABLE unrelated.employees (employee_id INTEGER);", expected_schema="public")
    with pytest.raises(PlanInputError):
        source_columns(b"CREATE TABLE public.a (id INTEGER); CREATE TABLE public.a (id INTEGER);", expected_schema="public")
