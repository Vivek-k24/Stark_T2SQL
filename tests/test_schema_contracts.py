"""DDL contract definitions only; no schema is applied by this module."""
import re


TABLES = frozenset({"divisions", "locations", "departments", "positions", "employees",
    "employee_compensation", "payroll_runs", "payroll_results", "payroll_earnings",
    "payroll_deductions", "leave_balances", "hr_bp_assignments"})


def ddl_without_comments(root):
    text = (root / "schema.sql").read_text(encoding="utf-8")
    return re.sub(r"--[^\n]*", "", text)


def test_schema_has_exact_twelve_tables_and_no_rows(project_root):
    text = ddl_without_comments(project_root)
    assert set(re.findall(r"CREATE TABLE public\.([a-z_]+)\s*\(", text)) == TABLES
    assert len(re.findall(r"CREATE TABLE", text)) == 12
    assert not re.search(r"\b(?:INSERT|COPY|UPDATE|DELETE)\b", text.replace("ON UPDATE", "").replace("ON DELETE", ""), re.I)


def test_money_dates_and_planted_edge_permissions(project_root):
    text = ddl_without_comments(project_root)
    assert "base_salary NUMERIC(14,2)" in text
    assert "bonus_target_pct NUMERIC(5,2)" in text
    assert "employee_number VARCHAR(6)" in text
    assert "'^S[0-9]{5}$'" in text
    assert "termination_date DATE" in text
    assert "DEFERRABLE INITIALLY IMMEDIATE" in text
    assert not re.search(r"\bDEFAULT\s+(?:CURRENT_DATE|CURRENT_TIMESTAMP|NOW\s*\()", text, re.I)
    assert not re.search(r"CHECK\s*\(\s*net_pay\s*>=\s*0", text, re.I)


def test_metadata_relations_match_expected_grain(schema_metadata):
    assert set(schema_metadata.columns_by_table) == TABLES
    assert ("payroll_run_id", "employee_id") in schema_metadata.table("payroll_results").unique_keys
    assert ("employee_id", "leave_type", "as_of_date") in schema_metadata.table("leave_balances").unique_keys
    fk = schema_metadata.table("employees").foreign_keys
    assert any(item.columns == ("manager_id",) and item.referenced_table == "employees" for item in fk)
