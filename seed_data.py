"""R02 deterministic synthetic fixture and explicitly authorized local reset.

Importing performs no generation, file writes, network or database work. Normal
generation uses a new review-authorized R02 baseline, not a reconstruction of
the unavailable historical dataset. The legacy externally bound configuration
loader remains available. The 18 operational checks are authored definitions,
not recovered historical checks. CLI defaults to an in-memory dry run.

Reset additionally requires an owner-supplied isolation proof and matching
live database COMMENT/OID/endpoint/schema binding. This module never creates
that authorization marker. It refuses unrelated objects and never truncates
with CASCADE. No live PostgreSQL acceptance is implied by offline exports.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, fields, is_dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import random
import re
import argparse
import importlib.metadata
import ipaddress
import os
import sys
import tempfile
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence


FIXTURE_VERSION = "spb_2026_10_12"
FIXTURE_DATE = date(2026, 10, 12)
FIXTURE_SEED = 42
EMPLOYEE_COUNT = 500
DIVISION_COUNT = 10
DEPARTMENT_COUNT = 37
ACTIVE_EMPLOYEE_COUNT = 435
CENT = Decimal("0.01")

# Frozen project physical contract; historical fidelity remains unverified.
TABLE_COLUMNS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "divisions": ("division_id", "division_code", "division_name"),
    "locations": ("location_id", "location_code", "location_name"),
    "departments": ("department_id", "division_id", "department_code", "department_name"),
    "positions": ("position_id", "position_code", "position_name"),
    "employees": (
        "employee_id", "employee_number", "first_name", "last_name", "email",
        "department_id", "position_id", "location_id", "manager_id", "hire_date",
        "termination_date", "status", "employment_type", "legal_entity",
    ),
    "employee_compensation": (
        "compensation_id", "employee_id", "effective_date", "effective_to",
        "base_salary", "bonus_target_pct", "currency_code",
    ),
    "payroll_runs": (
        "payroll_run_id", "run_number", "pay_period_start", "pay_period_end",
        "pay_date", "pay_frequency", "is_off_cycle", "status", "currency_code",
        "created_by_employee_id", "approved_by_employee_id", "approved_date",
        "total_gross_pay", "total_tax", "total_deductions", "total_net_pay",
    ),
    "payroll_results": (
        "payroll_result_id", "payroll_run_id", "employee_id", "gross_pay",
        "tax_amount", "total_deductions", "net_pay",
    ),
    "payroll_earnings": (
        "payroll_earning_id", "payroll_result_id", "line_number", "earning_code",
        "earning_type", "amount",
    ),
    "payroll_deductions": (
        "payroll_deduction_id", "payroll_result_id", "line_number",
        "deduction_code", "deduction_type", "amount",
    ),
    "leave_balances": (
        "leave_balance_id", "employee_id", "leave_type", "as_of_date", "balance_hours",
    ),
    "hr_bp_assignments": (
        "hr_bp_assignment_id", "employee_id", "division_id", "effective_from", "effective_to",
    ),
})
TABLE_PRIMARY_KEYS: Mapping[str, str] = MappingProxyType({
    name: columns[0] for name, columns in TABLE_COLUMNS.items()
})
HEADER_DETAIL_COLUMNS: Mapping[str, str] = MappingProxyType({
    "total_gross_pay": "gross_pay", "total_tax": "tax_amount",
    "total_deductions": "total_deductions", "total_net_pay": "net_pay",
})
_FIDELITY_SEAL = object()


class MissingSeedInputError(ValueError):
    """A required external seed/schema input is unavailable or incomplete."""


class FixtureInvariantError(ValueError):
    """Future generated rows fail a source-authored operational invariant."""


@dataclass(frozen=True, slots=True)
class SchemaFidelityBinding:
    project_root: Path
    project_schema_path: Path
    historical_schema_path: Path
    project_schema_sha256: str
    historical_schema_sha256: str
    review_reference: str
    approved_table_columns: Mapping[str, tuple[str, ...]]
    _seal: object


@dataclass(frozen=True, slots=True)
class CompensationPlan:
    employee_id: int
    first_effective_date: date
    current_effective_date: date
    effective_to: date | None


@dataclass(frozen=True, slots=True)
class CorrectionSelector:
    employee_id: int
    amount_sign: int


@dataclass(frozen=True, slots=True)
class PayrollPlan:
    payroll_run_id: int
    run_number: str
    pay_period_start: date
    pay_period_end: date
    pay_date: date
    is_off_cycle: bool
    status: str
    approved_by_employee_id: int | None
    approved_date: date | None
    employee_ids: tuple[int, ...]
    negative_net_employee_ids: tuple[int, ...]
    corrections: tuple[CorrectionSelector, ...]


@dataclass(frozen=True, slots=True)
class AmountGeneration:
    annual_salary_min: Decimal
    annual_salary_max: Decimal
    bonus_target_min: Decimal
    bonus_target_max: Decimal
    variable_earning_min: Decimal
    variable_earning_max: Decimal
    tax_pct_min: Decimal
    tax_pct_max: Decimal
    other_deduction_pct_min: Decimal
    other_deduction_pct_max: Decimal
    negative_net_excess_min: Decimal
    negative_net_excess_max: Decimal
    correction_amount_min: Decimal
    correction_amount_max: Decimal
    annual_pay_cycles: int


@dataclass(frozen=True, slots=True)
class LineVocabulary:
    base_code: str
    base_type: str
    variable_code: str
    variable_type: str
    correction_code: str
    correction_type: str


@dataclass(frozen=True, slots=True)
class DeductionVocabulary:
    tax_code: str
    tax_type: str
    other_code: str
    other_type: str


@dataclass(frozen=True, slots=True)
class SeedConfiguration:
    fidelity: SchemaFidelityBinding | None
    configuration_sha256: str
    divisions: tuple[Mapping[str, Any], ...]
    departments: tuple[Mapping[str, Any], ...]
    locations: tuple[Mapping[str, Any], ...]
    positions: tuple[Mapping[str, Any], ...]
    employees: tuple[Mapping[str, Any], ...]
    compensation_plans: tuple[CompensationPlan, ...]
    payroll_plans: tuple[PayrollPlan, ...]
    hr_assignments: tuple[Mapping[str, Any], ...]
    leave_employee_ids: tuple[int, ...]
    leave_types: tuple[str, ...]
    leave_snapshot_dates: tuple[date, ...]
    small_compensated_department_ids: tuple[int, ...]
    zero_tax_employee_ids: tuple[int, ...]
    zero_tax_population_definition: str
    mismatch_column: str
    mismatch_sign: int
    sales_division_id: int
    second_hr_principal_id: int
    amounts: AmountGeneration
    earning_vocabulary: LineVocabulary
    deduction_vocabulary: DeductionVocabulary
    leave_amount_min: Decimal
    leave_amount_max: Decimal


@dataclass(frozen=True, slots=True)
class GeneratedFixture:
    rows: Mapping[str, tuple[Mapping[str, Any], ...]]
    configuration_sha256: str
    fidelity: SchemaFidelityBinding | None

    def table(self, name: str) -> tuple[Mapping[str, Any], ...]:
        return self.rows.get(name, ())


@dataclass(frozen=True, slots=True)
class InvariantResult:
    invariant_id: str
    description: str
    satisfied: bool
    detail: str


@dataclass(frozen=True, slots=True)
class FixtureCreationSummary:
    fixture_version: str
    configuration_sha256: str
    historical_schema_sha256: str | None
    project_schema_sha256: str
    row_counts: Mapping[str, int]
    operational_invariants: tuple[InvariantResult, ...]
    database_verified: bool = False


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise MissingSeedInputError(label + " must be a supplied JSON object.")
    return value


def _need(record: Mapping[str, Any], key: str, label: str = "seed configuration") -> Any:
    if key not in record:
        raise MissingSeedInputError(label + " requires " + key + ".")
    return record[key]


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise MissingSeedInputError(label + " must be a nonempty owner-supplied string.")
    return value


def _positive_id(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise MissingSeedInputError(label + " must be a supplied positive integer identity.")
    return value


def _date(value: Any, label: str, *, nullable: bool = False) -> date | None:
    if value is None and nullable:
        return None
    if type(value) is not str:
        raise MissingSeedInputError(label + " requires an ISO calendar date.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MissingSeedInputError(label + " requires an ISO calendar date.") from exc
    if parsed.isoformat() != value:
        raise MissingSeedInputError(label + " must have the exact YYYY-MM-DD form.")
    return parsed


def _money(value: Any, label: str) -> Decimal:
    # Strings preserve external decimal input without a binary-float detour.
    if type(value) is not str:
        raise MissingSeedInputError(label + " requires an exact decimal string.")
    try:
        amount = Decimal(value)
    except Exception as exc:
        raise MissingSeedInputError(label + " requires an exact decimal string.") from exc
    if not amount.is_finite() or amount != amount.quantize(CENT, rounding=ROUND_HALF_UP):
        raise MissingSeedInputError(label + " must be finite with at most two decimal places.")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _sequence(value: Any, label: str) -> list[Any]:
    if type(value) is not list:
        raise MissingSeedInputError(label + " must be an explicitly supplied JSON array.")
    return value


def _ids(value: Any, label: str, *, allow_empty: bool = False) -> tuple[int, ...]:
    identities = tuple(_positive_id(item, label) for item in _sequence(value, label))
    if (not identities and not allow_empty) or len(set(identities)) != len(identities):
        raise MissingSeedInputError(label + " requires distinct supplied identities.")
    return tuple(sorted(identities))


def _inside(path: Path, root: Path, label: str) -> Path:
    resolved, resolved_root = path.resolve(), root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise MissingSeedInputError(label + " must be inside the intended project workspace.") from exc
    return resolved


def _file_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MissingSeedInputError(label + " is unavailable; supply the actual source input.") from exc


def _actual_digest(path: Path, recorded: Any, label: str) -> str:
    if type(recorded) is not str or re.fullmatch(r"[0-9a-f]{64}", recorded) is None:
        raise MissingSeedInputError(label + " requires a real recorded lowercase SHA-256 digest.")
    digest = hashlib.sha256(_file_bytes(path, label)).hexdigest()
    if digest != recorded:
        raise MissingSeedInputError(label + " no longer matches its supplied historical fidelity binding.")
    return digest


def _load_fidelity(raw: Any, *, project_root: Path) -> SchemaFidelityBinding:
    record = _object(raw, "schema_fidelity")
    root = project_root.resolve()
    project_path = _inside(root / _text(_need(record, "project_schema_path"), "project_schema_path"), root, "Project schema")
    historical_path = _inside(root / _text(_need(record, "historical_schema_path"), "historical_schema_path"), root, "Historical schema")
    if project_path != root / "schema.sql" or historical_path == project_path:
        raise MissingSeedInputError("A distinct actual historical DDL source and project schema.sql are required.")
    project_digest = _actual_digest(project_path, _need(record, "project_schema_sha256"), "Project schema")
    historical_digest = _actual_digest(historical_path, _need(record, "historical_schema_sha256"), "Historical schema")
    review = _text(_need(record, "fidelity_review_reference"), "fidelity_review_reference")
    shapes = _object(_need(record, "approved_table_columns"), "approved_table_columns")
    approved = {
        table: tuple(_text(column, "approved column") for column in _sequence(columns, "approved columns"))
        for table, columns in shapes.items()
    }
    if approved != dict(TABLE_COLUMNS):
        raise MissingSeedInputError("The owner-reviewed historical/project column mapping must match this draft physical contract.")
    return SchemaFidelityBinding(root, project_path, historical_path, project_digest,
                                 historical_digest, review, MappingProxyType(approved), _FIDELITY_SEAL)


def _reference_rows(raw: Any, table: str) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for item in _sequence(raw, table):
        record = _object(item, table + " row")
        if set(record) != set(TABLE_COLUMNS[table]):
            raise MissingSeedInputError(table + " requires exactly its authoritative reference columns.")
        row: dict[str, Any] = {}
        for column in TABLE_COLUMNS[table]:
            row[column] = _positive_id(record[column], column) if column.endswith("_id") else _text(record[column], column)
        rows.append(MappingProxyType(row))
    return tuple(sorted(rows, key=lambda row: row[TABLE_PRIMARY_KEYS[table]]))


def _employees(raw: Any) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for item in _sequence(raw, "employees"):
        record = _object(item, "employee")
        if set(record) != set(TABLE_COLUMNS["employees"]):
            raise MissingSeedInputError("Each authoritative employee plan requires the complete explicit identity/lifecycle layout.")
        row: dict[str, Any] = {}
        for column in TABLE_COLUMNS["employees"]:
            value = record[column]
            if column in {"hire_date", "termination_date"}:
                row[column] = _date(value, column, nullable=column == "termination_date")
            elif column.endswith("_id"):
                row[column] = None if column == "manager_id" and value is None else _positive_id(value, column)
            else:
                row[column] = _text(value, column)
        rows.append(MappingProxyType(row))
    return tuple(sorted(rows, key=lambda row: row["employee_id"]))


def _compensation_plans(raw: Any) -> tuple[CompensationPlan, ...]:
    plans: list[CompensationPlan] = []
    for item in _sequence(raw, "compensation_plans"):
        record = _object(item, "compensation plan")
        plans.append(CompensationPlan(
            _positive_id(_need(record, "employee_id"), "employee_id"),
            _date(_need(record, "first_effective_date"), "first_effective_date"),
            _date(_need(record, "current_effective_date"), "current_effective_date"),
            _date(_need(record, "effective_to"), "effective_to", nullable=True),
        ))
    return tuple(sorted(plans, key=lambda plan: plan.employee_id))


def _payroll_plans(raw: Any) -> tuple[PayrollPlan, ...]:
    plans: list[PayrollPlan] = []
    for item in _sequence(raw, "payroll_plans"):
        record = _object(item, "payroll plan")
        off_cycle = _need(record, "is_off_cycle")
        if type(off_cycle) is not bool:
            raise MissingSeedInputError("is_off_cycle must be an explicit boolean.")
        corrections: list[CorrectionSelector] = []
        for correction_raw in _sequence(_need(record, "corrections"), "corrections"):
            correction = _object(correction_raw, "correction selector")
            sign = _need(correction, "amount_sign")
            if type(sign) is not int or sign not in {-1, 1}:
                raise MissingSeedInputError("Correction signs are explicit owner layout inputs of -1 or 1.")
            corrections.append(CorrectionSelector(_positive_id(_need(correction, "employee_id"), "employee_id"), sign))
        approver = _need(record, "approved_by_employee_id")
        plans.append(PayrollPlan(
            _positive_id(_need(record, "payroll_run_id"), "payroll_run_id"),
            _text(_need(record, "run_number"), "run_number"),
            _date(_need(record, "pay_period_start"), "pay_period_start"),
            _date(_need(record, "pay_period_end"), "pay_period_end"),
            _date(_need(record, "pay_date"), "pay_date"),
            off_cycle, _text(_need(record, "status"), "status"),
            None if approver is None else _positive_id(approver, "approved_by_employee_id"),
            _date(_need(record, "approved_date"), "approved_date", nullable=True),
            _ids(_need(record, "employee_ids"), "payroll employee_ids"),
            _ids(_need(record, "negative_net_employee_ids"), "negative_net_employee_ids", allow_empty=True),
            tuple(sorted(corrections, key=lambda selector: selector.employee_id)),
        ))
    return tuple(sorted(plans, key=lambda plan: plan.payroll_run_id))


def _hr_assignments(raw: Any) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    columns = set(TABLE_COLUMNS["hr_bp_assignments"]) - {"hr_bp_assignment_id"}
    for item in _sequence(raw, "hr_assignments"):
        record = _object(item, "HR assignment")
        if set(record) != columns:
            raise MissingSeedInputError("HR assignment layout requires employee, division, start and explicit nullable end.")
        rows.append(MappingProxyType({
            "employee_id": _positive_id(record["employee_id"], "employee_id"),
            "division_id": _positive_id(record["division_id"], "division_id"),
            "effective_from": _date(record["effective_from"], "effective_from"),
            "effective_to": _date(record["effective_to"], "effective_to", nullable=True),
        }))
    return tuple(sorted(rows, key=lambda row: (row["employee_id"], row["division_id"], row["effective_from"])))


def _amount_generation(raw: Any) -> AmountGeneration:
    record = _object(raw, "amount_generation")
    monetary = tuple(field for field in AmountGeneration.__dataclass_fields__ if field != "annual_pay_cycles")
    values = {field: _money(_need(record, field), field) for field in monetary}
    cycles = _positive_id(_need(record, "annual_pay_cycles"), "annual_pay_cycles")
    return AmountGeneration(**values, annual_pay_cycles=cycles)


def load_seed_configuration(path: Path, *, project_root: Path) -> SeedConfiguration:
    """Future read-time dependency loader; never supplies a default fixture."""
    configuration_path = _inside(path, project_root, "Seed configuration")
    content = _file_bytes(configuration_path, "Authoritative seed configuration")
    try:
        raw = _object(json.loads(content), "seed configuration")
    except (ValueError, UnicodeError) as exc:
        raise MissingSeedInputError("A real owner-supplied seed configuration JSON file is required.") from exc
    fidelity = _load_fidelity(_need(raw, "schema_fidelity"), project_root=project_root)
    mismatch = _object(_need(raw, "header_mismatch"), "header_mismatch")
    mismatch_sign = _need(mismatch, "amount_sign")
    if type(mismatch_sign) is not int or mismatch_sign not in {-1, 1}:
        raise MissingSeedInputError("The PR-2026-012 mismatch sign requires an explicit owner selector.")
    earning = _object(_need(raw, "earning_vocabulary"), "earning_vocabulary")
    deductions = _object(_need(raw, "deduction_vocabulary"), "deduction_vocabulary")
    leave_bounds = _object(_need(raw, "leave_amount_bounds"), "leave_amount_bounds")
    config = SeedConfiguration(
        fidelity=fidelity, configuration_sha256=hashlib.sha256(content).hexdigest(),
        divisions=_reference_rows(_need(raw, "divisions"), "divisions"),
        departments=_reference_rows(_need(raw, "departments"), "departments"),
        locations=_reference_rows(_need(raw, "locations"), "locations"),
        positions=_reference_rows(_need(raw, "positions"), "positions"),
        employees=_employees(_need(raw, "employees")),
        compensation_plans=_compensation_plans(_need(raw, "compensation_plans")),
        payroll_plans=_payroll_plans(_need(raw, "payroll_plans")),
        hr_assignments=_hr_assignments(_need(raw, "hr_assignments")),
        leave_employee_ids=_ids(_need(raw, "leave_employee_ids"), "leave_employee_ids"),
        leave_types=tuple(_text(item, "leave type") for item in _sequence(_need(raw, "leave_types"), "leave_types")),
        leave_snapshot_dates=tuple(_date(item, "leave snapshot date") for item in _sequence(_need(raw, "leave_snapshot_dates"), "leave_snapshot_dates")),
        small_compensated_department_ids=_ids(_need(raw, "small_compensated_department_ids"), "small_compensated_department_ids"),
        zero_tax_employee_ids=_ids(_need(raw, "zero_tax_employee_ids"), "zero_tax_employee_ids"),
        zero_tax_population_definition=_text(_need(raw, "zero_tax_population_definition"), "zero_tax_population_definition"),
        mismatch_column=_text(_need(mismatch, "header_column"), "header_column"),
        mismatch_sign=mismatch_sign,
        sales_division_id=_positive_id(_need(raw, "sales_division_id"), "sales_division_id"),
        second_hr_principal_id=_positive_id(_need(raw, "second_hr_principal_id"), "second_hr_principal_id"),
        amounts=_amount_generation(_need(raw, "amount_generation")),
        earning_vocabulary=LineVocabulary(**{key: _text(_need(earning, key), key) for key in LineVocabulary.__dataclass_fields__}),
        deduction_vocabulary=DeductionVocabulary(**{key: _text(_need(deductions, key), key) for key in DeductionVocabulary.__dataclass_fields__}),
        leave_amount_min=_money(_need(leave_bounds, "minimum_hours"), "minimum_hours"),
        leave_amount_max=_money(_need(leave_bounds, "maximum_hours"), "maximum_hours"),
    )
    require_seed_contract(config)
    return config


def is_active(employee: Mapping[str, Any], as_of_date: date = FIXTURE_DATE) -> bool:
    """Canonical FR-7 headcount eligibility; no wall-clock fallback."""
    return (
        employee["hire_date"] <= as_of_date
        and (employee["termination_date"] is None or employee["termination_date"] > as_of_date)
        and employee["status"] != "cancelled_pre_hire"
        and employee["employment_type"] in ("full_time", "part_time")
    )


def require_seed_contract(config: SeedConfiguration) -> None:
    """Reject missing/provisional layout before future amount generation."""
    if type(config) is not SeedConfiguration or (config.fidelity is not None and config.fidelity._seal is not _FIDELITY_SEAL):
        raise MissingSeedInputError("A source-loaded owner configuration and historical schema fidelity binding are required.")
    if len(config.divisions) != DIVISION_COUNT or len(config.departments) != DEPARTMENT_COUNT or len(config.employees) != EMPLOYEE_COUNT:
        raise MissingSeedInputError("Owner layout must supply exactly 10 divisions, 37 departments and 500 employees.")
    if not config.locations or not config.positions:
        raise MissingSeedInputError("Authoritative locations and positions are required.")
    for table in ("divisions", "departments", "locations", "positions", "employees"):
        rows = getattr(config, table)
        key = TABLE_PRIMARY_KEYS[table]
        if len({row[key] for row in rows}) != len(rows):
            raise MissingSeedInputError(table + " contains duplicate supplied identities.")
    employees = {row["employee_id"]: row for row in config.employees}
    if not {326, 47, 361} <= set(employees):
        raise MissingSeedInputError("The FRD payroll/HR principal identities 326, 47 and 361 must be supplied.")
    if config.second_hr_principal_id not in {361, 364}:
        raise MissingSeedInputError("The second HR principal is 361, with 364 reserved for the conditional distinct-scope fallback.")
    if config.second_hr_principal_id not in employees:
        raise MissingSeedInputError("The configured conditional HR principal is absent from the supplied employee layout.")
    if sum(is_active(row) for row in config.employees) != ACTIVE_EMPLOYEE_COUNT:
        raise MissingSeedInputError("Supplied employee lifecycles must yield exactly 435 canonical active employees on 2026-10-12.")
    for row in config.employees:
        if re.fullmatch(r"S[0-9]{5}", row["employee_number"]) is None:
            raise MissingSeedInputError("Every supplied employee_number must be S followed by five digits.")
        if row["termination_date"] is not None and row["termination_date"] < row["hire_date"] and row["status"] != "cancelled_pre_hire":
            raise MissingSeedInputError("A supplied employee has an invalid lifecycle interval.")
    for field in ("employee_number", "email"):
        if len({row[field] for row in config.employees}) != EMPLOYEE_COUNT:
            raise MissingSeedInputError("Supplied employee " + field + " values must be unique.")
    references = {
        "department_id": {row["department_id"] for row in config.departments},
        "position_id": {row["position_id"] for row in config.positions},
        "location_id": {row["location_id"] for row in config.locations},
    }
    division_ids = {row["division_id"] for row in config.divisions}
    if config.sales_division_id not in division_ids or any(row["division_id"] not in division_ids for row in config.departments):
        raise MissingSeedInputError("Authoritative Sales/department division selectors must refer to supplied divisions.")
    for row in config.employees:
        if any(row[key] not in values for key, values in references.items()):
            raise MissingSeedInputError("An employee references an unavailable authoritative lookup identity.")
        if row["manager_id"] is not None and (row["manager_id"] not in employees or row["manager_id"] == row["employee_id"]):
            raise MissingSeedInputError("An employee has an unavailable/self manager identity.")
    if len(config.zero_tax_employee_ids) != 4 or not set(config.zero_tax_employee_ids) <= set(employees):
        raise MissingSeedInputError("Four actual owner-selected zero-tax employee identities are required.")
    # The FRD does not define whether no-payroll employees are included. Require
    # the owner to explicitly adopt the implemented nonempty-payee population.
    if config.zero_tax_population_definition != "employees_with_2026_payroll_rows":
        raise MissingSeedInputError("The zero-tax population definition is unresolved; this draft supports explicitly adopted employees_with_2026_payroll_rows only.")
    if len(config.small_compensated_department_ids) != 7 or not set(config.small_compensated_department_ids) <= references["department_id"]:
        raise MissingSeedInputError("Seven actual owner-selected small compensated department identities are required.")
    if config.mismatch_column not in HEADER_DETAIL_COLUMNS:
        raise MissingSeedInputError("The owner must select the PR-2026-012 header amount that differs from detail by 125.00.")
    if not config.leave_types or len(set(config.leave_types)) != len(config.leave_types):
        raise MissingSeedInputError("Distinct authoritative leave types are required.")
    if FIXTURE_DATE not in config.leave_snapshot_dates or len(set(config.leave_snapshot_dates)) != len(config.leave_snapshot_dates):
        raise MissingSeedInputError("Distinct leave snapshot dates must include the fixed fixture date.")
    if any(day > FIXTURE_DATE for day in config.leave_snapshot_dates) or not set(config.leave_employee_ids) <= set(employees):
        raise MissingSeedInputError("Leave layout contains future snapshots or unavailable employee identities.")
    if config.leave_amount_min > config.leave_amount_max:
        raise MissingSeedInputError("Leave bounds must be ordered.")
    plans = {plan.employee_id: plan for plan in config.compensation_plans}
    if len(plans) != len(config.compensation_plans) or not set(plans) <= set(employees):
        raise MissingSeedInputError("Compensation schedules require unique supplied employee identities.")
    for plan in plans.values():
        if plan.first_effective_date >= plan.current_effective_date or (plan.effective_to is not None and plan.effective_to <= plan.current_effective_date):
            raise MissingSeedInputError("Supplied compensation schedule endpoints must define nonoverlapping intervals.")
        if plan.first_effective_date < employees[plan.employee_id]["hire_date"]:
            raise MissingSeedInputError("Compensation must not begin before the supplied hire date.")
    runs = {plan.run_number: plan for plan in config.payroll_plans}
    if len(runs) != len(config.payroll_plans) or len({plan.payroll_run_id for plan in config.payroll_plans}) != len(runs):
        raise MissingSeedInputError("Payroll run names/identities must be distinct owner inputs.")
    required_runs = {"PR-2026-006", "PR-2026-012", "PR-2026-024"}
    if not required_runs <= set(runs):
        raise MissingSeedInputError("Owner payroll layout requires the three FRD planted-fact run numbers.")
    if len(runs["PR-2026-006"].negative_net_employee_ids) != 3:
        raise MissingSeedInputError("PR-2026-006 requires three supplied negative-net employee selectors.")
    correction_run = runs["PR-2026-024"]
    if not correction_run.is_off_cycle or correction_run.status != "approved" or len(correction_run.corrections) != 4 or len(correction_run.employee_ids) != 4:
        raise MissingSeedInputError("PR-2026-024 requires explicit approved off-cycle layout and four corrections.")
    for run in runs.values():
        if not set(run.employee_ids) <= set(employees) or not set(run.negative_net_employee_ids) <= set(run.employee_ids):
            raise MissingSeedInputError("Payroll layout references unavailable employees or negative-net selectors.")
        correction_ids = tuple(selector.employee_id for selector in run.corrections)
        if len(set(correction_ids)) != len(correction_ids) or (run.corrections and set(correction_ids) != set(run.employee_ids)):
            raise MissingSeedInputError("A correction run must name one explicit signed correction per payee.")
        if run.corrections and not run.is_off_cycle:
            raise MissingSeedInputError("Corrections require an owner-declared off-cycle run.")
        if run.pay_period_start > run.pay_period_end or run.pay_date < run.pay_period_end:
            raise MissingSeedInputError("Payroll period/payment dates must be explicit and ordered.")
        if run.approved_by_employee_id is not None and run.approved_by_employee_id not in employees:
            raise MissingSeedInputError("The payroll approver identity is not supplied.")
        if (run.approved_date is None) != (run.approved_by_employee_id is None):
            raise MissingSeedInputError("Approval date and approver must both be supplied or both be absent.")
        if run.run_number != "PR-2026-006" and run.negative_net_employee_ids:
            raise MissingSeedInputError("This draft reserves the negative-net planting selector for PR-2026-006.")
        for employee_id in run.employee_ids:
            if not run.corrections and employee_id not in plans:
                raise MissingSeedInputError("Every regular payroll payee requires an authoritative compensation schedule.")
            employee = employees[employee_id]
            if not run.corrections and (employee["hire_date"] > run.pay_period_end or employee["status"] == "cancelled_pre_hire" or (employee["termination_date"] is not None and employee["termination_date"] < run.pay_period_start)):
                raise MissingSeedInputError("Regular payroll eligibility contradicts an owner employee lifecycle.")
    amounts = config.amounts
    pairs = (
        (amounts.annual_salary_min, amounts.annual_salary_max),
        (amounts.bonus_target_min, amounts.bonus_target_max),
        (amounts.variable_earning_min, amounts.variable_earning_max),
        (amounts.tax_pct_min, amounts.tax_pct_max),
        (amounts.other_deduction_pct_min, amounts.other_deduction_pct_max),
        (amounts.negative_net_excess_min, amounts.negative_net_excess_max),
        (amounts.correction_amount_min, amounts.correction_amount_max),
    )
    if any(lower < 0 or lower > upper or not lower.is_finite() or not upper.is_finite() for lower, upper in pairs):
        raise MissingSeedInputError("All monetary/percentage generation bounds must be finite, nonnegative and ordered.")
    if amounts.annual_salary_min <= 0 or amounts.tax_pct_min <= 0 or amounts.negative_net_excess_min <= 0 or amounts.correction_amount_min <= 0:
        raise MissingSeedInputError("Salary, ordinary tax, negative-net excess and correction lower bounds must be positive.")
    if amounts.bonus_target_max > 100 or amounts.tax_pct_max + amounts.other_deduction_pct_max > 100:
        raise MissingSeedInputError("Bonus/ordinary deduction percentages must remain within their physical and nonnegative-net contracts.")
    if amounts.annual_pay_cycles != 26:
        raise MissingSeedInputError("This annual-salary biweekly draft requires an explicitly supplied 26-cycle conversion; other historical layouts require reconciliation.")


def _draw(rng: random.Random, minimum: Decimal, maximum: Decimal) -> Decimal:
    return Decimal(rng.randint(int(minimum * 100), int(maximum * 100))) / 100


def _cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _compensation_on(rows: Sequence[Mapping[str, Any]], employee_id: int, day: date) -> Mapping[str, Any]:
    matches = [row for row in rows if row["employee_id"] == employee_id and row["effective_date"] <= day and (row["effective_to"] is None or day < row["effective_to"])]
    if len(matches) != 1:
        raise MissingSeedInputError("A payroll date does not resolve exactly one owner-defined compensation interval.")
    return matches[0]


def generate_fixture(config: SeedConfiguration | None = None, *, seed: int = FIXTURE_SEED,
                     as_of_date: date = FIXTURE_DATE) -> GeneratedFixture:
    """Generate the reviewed R02 baseline in memory, without a database."""
    if type(seed) is not int or seed != FIXTURE_SEED or type(as_of_date) is not date or as_of_date != FIXTURE_DATE:
        raise MissingSeedInputError("R02 requires seed 42 and as-of date 2026-10-12.")
    if config is None:
        config = default_seed_configuration()
    require_seed_contract(config)
    # Re-read actual schema inputs later to reject stale source/config bindings.
    if config.fidelity is not None:
        _actual_digest(config.fidelity.project_schema_path, config.fidelity.project_schema_sha256, "Project schema")
        _actual_digest(config.fidelity.historical_schema_path, config.fidelity.historical_schema_sha256, "Historical schema")
    rng = random.Random(FIXTURE_SEED)
    data: dict[str, list[Mapping[str, Any]]] = {table: [] for table in TABLE_COLUMNS}
    for table in ("divisions", "departments", "locations", "positions", "employees"):
        data[table].extend(dict(row) for row in getattr(config, table))
    amounts, vocabulary, deductions = config.amounts, config.earning_vocabulary, config.deduction_vocabulary
    for plan in config.compensation_plans:
        for start, end in ((plan.first_effective_date, plan.current_effective_date), (plan.current_effective_date, plan.effective_to)):
            data["employee_compensation"].append({
                "compensation_id": len(data["employee_compensation"]) + 1,
                "employee_id": plan.employee_id, "effective_date": start, "effective_to": end,
                "base_salary": _draw(rng, amounts.annual_salary_min, amounts.annual_salary_max),
                "bonus_target_pct": _draw(rng, amounts.bonus_target_min, amounts.bonus_target_max),
                "currency_code": "USD",
            })
    zero_tax = set(config.zero_tax_employee_ids)
    for plan in config.payroll_plans:
        run_results: list[Mapping[str, Any]] = []
        correction_signs = {selector.employee_id: selector.amount_sign for selector in plan.corrections}
        for employee_id in plan.employee_ids:
            correction = employee_id in correction_signs
            if correction:
                base_amount = _draw(rng, amounts.correction_amount_min, amounts.correction_amount_max) * correction_signs[employee_id]
                variable_amount = Decimal("0.00")
            else:
                compensation = _compensation_on(data["employee_compensation"], employee_id, plan.pay_period_end)
                base_amount = _cents(compensation["base_salary"] / amounts.annual_pay_cycles)
                variable_amount = _draw(rng, amounts.variable_earning_min, amounts.variable_earning_max)
            gross = _cents(base_amount + variable_amount)
            ordinary_positive = max(gross, Decimal("0.00"))
            tax = Decimal("0.00") if employee_id in zero_tax or ordinary_positive == 0 else max(CENT, _cents(ordinary_positive * _draw(rng, amounts.tax_pct_min, amounts.tax_pct_max) / 100))
            other = _cents(ordinary_positive * _draw(rng, amounts.other_deduction_pct_min, amounts.other_deduction_pct_max) / 100)
            if employee_id in plan.negative_net_employee_ids:
                other = _cents(gross - tax + _draw(rng, amounts.negative_net_excess_min, amounts.negative_net_excess_max))
            elif gross > 0:
                other = min(other, max(Decimal("0.00"), gross - tax))
            total_deductions = _cents(tax + other)
            result_id = len(data["payroll_results"]) + 1
            result = {
                "payroll_result_id": result_id, "payroll_run_id": plan.payroll_run_id,
                "employee_id": employee_id, "gross_pay": gross, "tax_amount": tax,
                "total_deductions": total_deductions, "net_pay": _cents(gross - total_deductions),
            }
            data["payroll_results"].append(result)
            run_results.append(result)
            earning_lines = [(vocabulary.correction_code, vocabulary.correction_type, gross)] if correction else [
                (vocabulary.base_code, vocabulary.base_type, base_amount),
                (vocabulary.variable_code, vocabulary.variable_type, variable_amount),
            ]
            for line_number, (code, kind, amount) in enumerate(earning_lines, start=1):
                data["payroll_earnings"].append({
                    "payroll_earning_id": len(data["payroll_earnings"]) + 1,
                    "payroll_result_id": result_id, "line_number": line_number,
                    "earning_code": code, "earning_type": kind, "amount": _cents(amount),
                })
            for line_number, (code, kind, amount) in enumerate((
                (deductions.tax_code, deductions.tax_type, tax),
                (deductions.other_code, deductions.other_type, other),
            ), start=1):
                data["payroll_deductions"].append({
                    "payroll_deduction_id": len(data["payroll_deductions"]) + 1,
                    "payroll_result_id": result_id, "line_number": line_number,
                    "deduction_code": code, "deduction_type": kind, "amount": _cents(amount),
                })
        run = {
            "payroll_run_id": plan.payroll_run_id, "run_number": plan.run_number,
            "pay_period_start": plan.pay_period_start, "pay_period_end": plan.pay_period_end,
            "pay_date": plan.pay_date, "pay_frequency": "biweekly", "is_off_cycle": plan.is_off_cycle,
            "status": plan.status, "currency_code": "USD", "created_by_employee_id": 326,
            "approved_by_employee_id": plan.approved_by_employee_id, "approved_date": plan.approved_date,
        }
        for header, detail in HEADER_DETAIL_COLUMNS.items():
            run[header] = _cents(sum((row[detail] for row in run_results), Decimal("0.00")))
        if plan.run_number == "PR-2026-012":
            run[config.mismatch_column] += Decimal("125.00") * config.mismatch_sign
        data["payroll_runs"].append(run)
    for employee_id in config.leave_employee_ids:
        for leave_type in sorted(config.leave_types):
            for day in sorted(config.leave_snapshot_dates):
                data["leave_balances"].append({
                    "leave_balance_id": len(data["leave_balances"]) + 1,
                    "employee_id": employee_id, "leave_type": leave_type, "as_of_date": day,
                    "balance_hours": _draw(rng, config.leave_amount_min, config.leave_amount_max),
                })
    for row in config.hr_assignments:
        data["hr_bp_assignments"].append({"hr_bp_assignment_id": len(data["hr_bp_assignments"]) + 1, **row})
    immutable = MappingProxyType({table: tuple(MappingProxyType(dict(row)) for row in rows) for table, rows in data.items()})
    generated = GeneratedFixture(immutable, config.configuration_sha256, config.fidelity)
    require_invariants(generated, config)
    return generated


def _result(number: int, description: str, satisfied: bool, detail: str = "") -> InvariantResult:
    return InvariantResult("DRAFT-FIXTURE-" + str(number).zfill(2), description, bool(satisfied), detail)


def check_01_table_contract(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    valid = set(fixture.rows) == set(TABLE_COLUMNS) and all(set(row) == set(TABLE_COLUMNS[table]) for table in TABLE_COLUMNS for row in fixture.table(table))
    return _result(1, "Exactly twelve reviewed table/column contracts", valid)


def check_02_reference_cardinality(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    valid = len(fixture.table("divisions")) == DIVISION_COUNT and len(fixture.table("departments")) == DEPARTMENT_COUNT and bool(fixture.table("locations")) and bool(fixture.table("positions"))
    for table in ("divisions", "departments", "positions", "locations"):
        rows, pk = fixture.table(table), TABLE_PRIMARY_KEYS[table]
        valid = valid and len({row[pk] for row in rows}) == len(rows)
        code = table[:-1] + "_code" if table != "departments" else "department_code"
        valid = valid and len({row[code] for row in rows}) == len(rows)
    return _result(2, "Reviewed lookup identities and 10/37 cardinalities", valid)


def check_03_employee_identity(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    rows = fixture.table("employees")
    valid = len(rows) == EMPLOYEE_COUNT and {326, 47, 361} <= {row["employee_id"] for row in rows}
    for key in ("employee_id", "employee_number", "email"):
        valid = valid and len({row[key] for row in rows}) == len(rows)
    valid = valid and all(type(row["employee_id"]) is int and row["employee_id"] > 0 and re.fullmatch(r"S[0-9]{5}", row["employee_number"]) is not None for row in rows)
    return _result(3, "500 distinct synthetic employee identities", valid)


def check_04_relationship_keys(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    relations = (
        ("departments", "division_id", "divisions", "division_id"),
        ("employees", "department_id", "departments", "department_id"),
        ("employees", "position_id", "positions", "position_id"),
        ("employees", "location_id", "locations", "location_id"),
        ("employees", "manager_id", "employees", "employee_id"),
        ("employee_compensation", "employee_id", "employees", "employee_id"),
        ("payroll_runs", "created_by_employee_id", "employees", "employee_id"),
        ("payroll_runs", "approved_by_employee_id", "employees", "employee_id"),
        ("payroll_results", "payroll_run_id", "payroll_runs", "payroll_run_id"),
        ("payroll_results", "employee_id", "employees", "employee_id"),
        ("payroll_earnings", "payroll_result_id", "payroll_results", "payroll_result_id"),
        ("payroll_deductions", "payroll_result_id", "payroll_results", "payroll_result_id"),
        ("leave_balances", "employee_id", "employees", "employee_id"),
        ("hr_bp_assignments", "employee_id", "employees", "employee_id"),
        ("hr_bp_assignments", "division_id", "divisions", "division_id"),
    )
    valid = True
    for table, column, target, target_column in relations:
        allowed = {row[target_column] for row in fixture.table(target)}
        valid = valid and all(row[column] is None or row[column] in allowed for row in fixture.table(table))
    for table in TABLE_COLUMNS:
        rows, key = fixture.table(table), TABLE_PRIMARY_KEYS[table]
        valid = valid and len({row[key] for row in rows}) == len(rows) and all(type(row[key]) is int and row[key] > 0 for row in rows)
    return _result(4, "All surrogate identities and physical foreign keys", valid)


def check_05_employee_lifecycle(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    rows = fixture.table("employees")
    valid = sum(is_active(row) for row in rows) == ACTIVE_EMPLOYEE_COUNT
    valid = valid and all(row["termination_date"] is None or row["termination_date"] >= row["hire_date"] or row["status"] == "cancelled_pre_hire" for row in rows)
    return _result(5, "435 canonical active employees at explicit fixture date", valid)


def check_06_manager_graph(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    employees = {row["employee_id"]: row for row in fixture.table("employees")}
    valid = True
    for employee_id in employees:
        chain: set[int] = set()
        current = employee_id
        while current is not None:
            if current in chain or current not in employees:
                valid = False
                break
            chain.add(current)
            current = employees[current]["manager_id"]
    departments = {row["department_id"]: row["division_id"] for row in fixture.table("departments")}
    managers = {row["manager_id"] for row in employees.values() if row["manager_id"] is not None}
    valid = valid and any(employee_id in managers and is_active(row) and departments.get(row["department_id"]) == config.sales_division_id for employee_id, row in employees.items())
    return _result(6, "Acyclic managers and derivable active Sales manager", valid)


def check_07_compensation_intervals(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    groups: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    valid = bool(fixture.table("employee_compensation"))
    for row in fixture.table("employee_compensation"):
        groups[row["employee_id"]].append(row)
        valid = valid and row["currency_code"] == "USD" and isinstance(row["base_salary"], Decimal) and row["base_salary"].is_finite() and row["base_salary"] >= 0 and isinstance(row["bonus_target_pct"], Decimal) and row["bonus_target_pct"].is_finite() and 0 <= row["bonus_target_pct"] <= 100
        valid = valid and (row["effective_to"] is None or row["effective_to"] > row["effective_date"])
    for rows in groups.values():
        ordered = sorted(rows, key=lambda row: row["effective_date"])
        valid = valid and len({row["effective_date"] for row in rows}) == len(rows) and sum(row["effective_to"] is None for row in rows) <= 1
        valid = valid and all(left["effective_to"] is not None and left["effective_to"] <= right["effective_date"] for left, right in zip(ordered, ordered[1:]))
    return _result(7, "Annual USD compensation with nonoverlapping effective ranges", valid)


def check_08_payroll_cadence(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    runs = fixture.table("payroll_runs")
    valid = bool(runs) and len({row["run_number"] for row in runs}) == len(runs)
    valid = valid and all(row["currency_code"] == "USD" and row["pay_frequency"] == "biweekly" and row["pay_period_start"] <= row["pay_period_end"] <= row["pay_date"] for row in runs)
    normal = sorted((row for row in runs if not row["is_off_cycle"]), key=lambda row: row["pay_period_start"])
    valid = valid and all((row["pay_period_end"] - row["pay_period_start"]).days == 13 for row in normal)
    valid = valid and all((right["pay_period_start"] - left["pay_period_start"]).days == 14 and (right["pay_date"] - left["pay_date"]).days == 14 for left, right in zip(normal, normal[1:]))
    return _result(8, "Explicit regular biweekly periods and USD-only payroll", valid)


def check_09_payroll_approval(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    valid = all(row["created_by_employee_id"] == 326 and (row["approved_by_employee_id"] is None) == (row["approved_date"] is None) and (row["approved_date"] is None or row["approved_date"] <= row["pay_date"]) for row in fixture.table("payroll_runs"))
    return _result(9, "FRD payroll creator and explicit approval identity/date pairs", valid)


def check_10_payroll_result_grain(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    rows = fixture.table("payroll_results")
    valid = bool(rows) and len({(row["payroll_run_id"], row["employee_id"]) for row in rows}) == len(rows)
    valid = valid and all(all(isinstance(row[column], Decimal) and row[column].is_finite() and row[column] == _cents(row[column]) for column in HEADER_DETAIL_COLUMNS.values()) and row["net_pay"] == _cents(row["gross_pay"] - row["total_deductions"]) for row in rows)
    return _result(10, "Unique run/employee result grain and exact-cent net arithmetic", valid)


def _lines_reconcile(fixture: GeneratedFixture, table: str, target_column: str) -> bool:
    lines: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in fixture.table(table):
        lines[row["payroll_result_id"]].append(row)
    for result in fixture.table("payroll_results"):
        group = lines[result["payroll_result_id"]]
        if not group or len({row["line_number"] for row in group}) != len(group) or any(row["line_number"] <= 0 or not isinstance(row["amount"], Decimal) or not row["amount"].is_finite() for row in group):
            return False
        if sum((row["amount"] for row in group), Decimal("0.00")) != result[target_column]:
            return False
    return bool(fixture.table("payroll_results"))


def check_11_earnings_reconciliation(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    return _result(11, "Earning lines reconcile exactly to each result gross", _lines_reconcile(fixture, "payroll_earnings", "gross_pay"))


def check_12_deductions_reconciliation(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    valid = _lines_reconcile(fixture, "payroll_deductions", "total_deductions")
    lines: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in fixture.table("payroll_deductions"):
        if row["deduction_code"] == config.deduction_vocabulary.tax_code and row["deduction_type"] == config.deduction_vocabulary.tax_type:
            lines[row["payroll_result_id"]] += row["amount"]
    valid = valid and all(lines[row["payroll_result_id"]] == row["tax_amount"] for row in fixture.table("payroll_results"))
    return _result(12, "Deduction lines include exact recorded tax and reconcile", valid)


def check_13_negative_net_fact(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    runs = {row["run_number"]: row["payroll_run_id"] for row in fixture.table("payroll_runs")}
    selected = {row["employee_id"] for row in fixture.table("payroll_results") if row["payroll_run_id"] == runs.get("PR-2026-006") and row["net_pay"] < 0}
    plans = {plan.run_number: plan for plan in config.payroll_plans}
    expected = set(plans["PR-2026-006"].negative_net_employee_ids) if "PR-2026-006" in plans else set()
    return _result(13, "Exactly three configured negative nets in PR-2026-006", len(selected) == 3 and selected == expected)


def check_14_zero_annual_tax_fact(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    year_runs = {row["payroll_run_id"] for row in fixture.table("payroll_runs") if row["pay_date"].year == 2026}
    taxes: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in fixture.table("payroll_results"):
        if row["payroll_run_id"] in year_runs:
            taxes[row["employee_id"]] += row["tax_amount"]
    selected = {employee_id for employee_id, total in taxes.items() if total == 0}
    valid = config.zero_tax_population_definition == "employees_with_2026_payroll_rows" and len(selected) == 4 and selected == set(config.zero_tax_employee_ids)
    return _result(14, "Exactly four configured zero-tax 2026 payees under explicit population definition", valid)


def check_15_header_mismatch_fact(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    totals: dict[int, dict[str, Decimal]] = defaultdict(lambda: {column: Decimal("0.00") for column in HEADER_DETAIL_COLUMNS.values()})
    for row in fixture.table("payroll_results"):
        for column in HEADER_DETAIL_COLUMNS.values():
            totals[row["payroll_run_id"]][column] += row[column]
    mismatches: list[tuple[str, str, Decimal]] = []
    for run in fixture.table("payroll_runs"):
        for header, detail in HEADER_DETAIL_COLUMNS.items():
            difference = run[header] - totals[run["payroll_run_id"]][detail]
            if difference != 0:
                mismatches.append((run["run_number"], header, difference))
    expected = [("PR-2026-012", config.mismatch_column, Decimal("125.00") * config.mismatch_sign)]
    return _result(15, "Only PR-2026-012 has the configured 125.00 header/detail difference", mismatches == expected)


def check_16_off_cycle_corrections_fact(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    run = next((row for row in fixture.table("payroll_runs") if row["run_number"] == "PR-2026-024"), None)
    plan = next((item for item in config.payroll_plans if item.run_number == "PR-2026-024"), None)
    if run is None or plan is None:
        return _result(16, "PR-2026-024 is approved, off-cycle and four explicit corrections", False)
    results = [row for row in fixture.table("payroll_results") if row["payroll_run_id"] == run["payroll_run_id"]]
    result_ids = {row["payroll_result_id"] for row in results}
    lines = [row for row in fixture.table("payroll_earnings") if row["payroll_result_id"] in result_ids]
    valid = run["is_off_cycle"] is True and run["status"] == "approved" and run["approved_by_employee_id"] is not None and run["approved_date"] is not None
    valid = valid and len(results) == 4 and len(lines) == 4 and {row["employee_id"] for row in results} == {selector.employee_id for selector in plan.corrections}
    valid = valid and all(row["earning_code"] == config.earning_vocabulary.correction_code and row["earning_type"] == config.earning_vocabulary.correction_type for row in lines)
    return _result(16, "PR-2026-024 is approved, off-cycle and four explicit corrections", valid)


def check_17_small_compensated_departments(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    active = {row["employee_id"]: row for row in fixture.table("employees") if is_active(row)}
    current = {row["employee_id"] for row in fixture.table("employee_compensation") if row["effective_date"] <= FIXTURE_DATE and (row["effective_to"] is None or FIXTURE_DATE < row["effective_to"])}
    counts: dict[int, int] = {row["department_id"]: 0 for row in fixture.table("departments")}
    for employee_id in current & set(active):
        counts[active[employee_id]["department_id"]] += 1
    small = {department_id for department_id, count in counts.items() if count < 5}
    return _result(17, "Exactly seven configured departments below five active/current compensated employees", len(small) == 7 and small == set(config.small_compensated_department_ids))


def check_18_leave_and_hr_scopes(fixture: GeneratedFixture, config: SeedConfiguration) -> InvariantResult:
    leave = fixture.table("leave_balances")
    valid = bool(leave) and len({(row["employee_id"], row["leave_type"], row["as_of_date"]) for row in leave}) == len(leave)
    valid = valid and all(row["as_of_date"] <= FIXTURE_DATE and isinstance(row["balance_hours"], Decimal) and row["balance_hours"].is_finite() for row in leave)
    assignments = fixture.table("hr_bp_assignments")
    valid = valid and len({(row["employee_id"], row["division_id"], row["effective_from"]) for row in assignments}) == len(assignments)
    current: dict[int, set[int]] = defaultdict(set)
    intervals: dict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in assignments:
        valid = valid and (row["effective_to"] is None or row["effective_to"] > row["effective_from"])
        intervals[(row["employee_id"], row["division_id"])].append(row)
        # FR-6 uses effective_to IS NULL, so future-start open assignments
        # must not be planted as apparently current principal grants.
        if row["effective_to"] is None:
            valid = valid and row["effective_from"] <= FIXTURE_DATE
            current[row["employee_id"]].add(row["division_id"])
    for rows in intervals.values():
        ordered = sorted(rows, key=lambda row: row["effective_from"])
        valid = valid and all(left["effective_to"] is not None and left["effective_to"] <= right["effective_from"] for left, right in zip(ordered, ordered[1:]))
    # Match the existing fixed persona resolver: 364 is considered only
    # after 47/361 fail to supply two distinct nonempty scopes. It can replace
    # either missing/nondistinct scope, preserving the other original scope.
    first, second = 47, 361
    if not current[first] or not current[second] or current[first] == current[second]:
        if current[47] and current[364] and current[47] != current[364]:
            first, second = 47, 364
        elif current[361] and current[364] and current[361] != current[364]:
            first, second = 364, 361
        else:
            valid = False
    valid = valid and bool(current[first]) and bool(current[second]) and current[first] != current[second]
    valid = valid and second == config.second_hr_principal_id
    return _result(18, "Dated leave snapshots and distinct HR scopes with conditional 364 fallback", valid)


# These are the eighteen authored operational definitions, not historical
# evidence and not the recovered authoritative invariant list.
OPERATIONAL_INVARIANTS: tuple[Callable[[GeneratedFixture, SeedConfiguration], InvariantResult], ...] = (
    check_01_table_contract, check_02_reference_cardinality, check_03_employee_identity,
    check_04_relationship_keys, check_05_employee_lifecycle, check_06_manager_graph,
    check_07_compensation_intervals, check_08_payroll_cadence, check_09_payroll_approval,
    check_10_payroll_result_grain, check_11_earnings_reconciliation,
    check_12_deductions_reconciliation, check_13_negative_net_fact,
    check_14_zero_annual_tax_fact, check_15_header_mismatch_fact,
    check_16_off_cycle_corrections_fact, check_17_small_compensated_departments,
    check_18_leave_and_hr_scopes,
)


def evaluate_invariants(fixture: GeneratedFixture, config: SeedConfiguration | None = None) -> tuple[InvariantResult, ...]:
    """Future pure row evaluation; never claims empirical security/accuracy."""
    if config is None:
        config = default_seed_configuration()
    results: list[InvariantResult] = []
    for index, invariant in enumerate(OPERATIONAL_INVARIANTS, start=1):
        try:
            results.append(invariant(fixture, config))
        except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError) as exc:
            results.append(_result(index, invariant.__name__, False, "Input layout prevents evaluation: " + type(exc).__name__))
    return tuple(results)


def require_invariants(fixture: GeneratedFixture, config: SeedConfiguration) -> tuple[InvariantResult, ...]:
    results = evaluate_invariants(fixture, config)
    failures = [result.invariant_id for result in results if not result.satisfied]
    if failures:
        raise FixtureInvariantError("Future generated rows violate authored operational invariants: " + ", ".join(failures))
    return results


def _require_database_shape(cursor: Any) -> None:
    cursor.execute(
        "SELECT relation.relname, attribute.attname FROM pg_catalog.pg_class AS relation "
        "JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
        "JOIN pg_catalog.pg_attribute AS attribute ON attribute.attrelid = relation.oid "
        "WHERE namespace.nspname = 'public' AND relation.relkind IN ('r','p') "
        "AND attribute.attnum > 0 AND NOT attribute.attisdropped "
        "ORDER BY relation.relname, attribute.attnum"
    )
    found: dict[str, list[str]] = defaultdict(list)
    for table, column in cursor.fetchall():
        found[table].append(column)
    if {table: tuple(columns) for table, columns in found.items()} != dict(TABLE_COLUMNS):
        raise MissingSeedInputError("The actual target database does not match the owner-bound twelve-table physical contract.")


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, Decimal, Path)):
        return str(value)
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(_json_value(value), sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def default_seed_configuration() -> SeedConfiguration:
    """New R02 layout; names/selectors are not claimed as historical identities.

    A private Faker instance has seed 42 rather than altering Faker's global
    random state. Reproduction requires the Faker version recorded in manifest.
    """
    from faker import Faker

    fake = Faker(locale="en_US")
    fake.seed_instance(FIXTURE_SEED)
    rng = random.Random(FIXTURE_SEED)
    names = ("Sales", "Engineering", "Finance", "Human Resources", "Operations",
             "Marketing", "Legal", "Customer Success", "Research", "Strategy")
    divisions = tuple({"division_id": i, "division_code": f"DIV{i:02d}", "division_name": name}
                      for i, name in enumerate(names, 1))
    departments = tuple({"department_id": i, "division_id": (i - 1) % 10 + 1,
                         "department_code": f"DEP{i:02d}", "department_name": f"{names[(i - 1) % 10]} Team {i:02d}"}
                        for i in range(1, 38))
    locations = tuple({"location_id": i, "location_code": f"LOC{i:02d}", "location_name": fake.city()}
                      for i in range(1, 8))
    positions = tuple({"position_id": i, "position_code": f"POS{i:02d}", "position_name": fake.unique.job()}
                      for i in range(1, 21))
    employees = []
    for i in range(1, 501):
        hired = date(2019, 1, 1) + timedelta(days=rng.randrange(1500))
        terminated, status = None, "active"
        if 436 <= i <= 475:
            terminated, status = date(2026, 7, 1), "terminated"
        elif 476 <= i <= 490:
            hired, status = date(2026, 11, 1), "pending_hire"
        elif i >= 491:
            hired, terminated, status = date(2026, 11, 1), date(2026, 10, 1), "cancelled_pre_hire"
        employees.append({
            "employee_id": i, "employee_number": f"S{i:05d}",
            "first_name": fake.first_name(), "last_name": fake.last_name(),
            "email": f"employee{i:05d}@starkcorp.example.com",
            "department_id": (i - 1) // 3 + 1 if i <= 21 else 8 + (i - 22) % 30,
            "position_id": rng.randrange(1, 21), "location_id": rng.randrange(1, 8),
            "manager_id": None if i == 1 else (i - 2) // 10 + 1,
            "hire_date": hired, "termination_date": terminated, "status": status,
            "employment_type": "part_time" if i % 5 == 0 else "full_time",
            "legal_entity": "Stark Synthetic LLC",
        })
    compensation = tuple(CompensationPlan(e["employee_id"], e["hire_date"], date(2025, 1, 1), e["termination_date"])
                         for e in employees if e["employee_id"] <= 475)
    payroll = []
    for i in range(1, 21):
        start = date(2026, 1, 2) + timedelta(days=14 * (i - 1))
        end, payday = start + timedelta(days=13), start + timedelta(days=15)
        payees = tuple(e["employee_id"] for e in employees if e["hire_date"] <= end
                       and e["status"] != "cancelled_pre_hire"
                       and (e["termination_date"] is None or end < e["termination_date"]))
        payroll.append(PayrollPlan(i, f"PR-2026-{i:03d}", start, end, payday, False,
                                  "posted" if i == 20 else "closed", 1, payday,
                                  payees, (5, 6, 7) if i == 6 else (), ()))
    payroll.append(PayrollPlan(24, "PR-2026-024", date(2026, 10, 10), FIXTURE_DATE, FIXTURE_DATE,
                              True, "approved", 1, FIXTURE_DATE, (1, 2, 3, 4), (),
                              tuple(CorrectionSelector(i, -1 if i == 3 else 1) for i in range(1, 5))))
    assignments = tuple({"employee_id": principal, "division_id": division,
                         "effective_from": date(2025, 1, 1), "effective_to": None}
                        for principal, scope in ((47, (1, 2)), (361, (3, 4)), (364, (5, 6)))
                        for division in scope)
    config = SeedConfiguration(
        None, "", divisions, departments, locations, positions, tuple(employees), compensation,
        tuple(payroll), assignments, tuple(range(1, 436)), ("annual", "personal", "sick"),
        (date(2026, 9, 30), FIXTURE_DATE), tuple(range(1, 8)), (10, 20, 30, 40),
        "employees_with_2026_payroll_rows", "total_gross_pay", 1, 1, 361,
        AmountGeneration(*(Decimal(value) for value in (
            "42000", "210000", "0", "25", "0", "350", "12", "28", "2", "8",
            "50", "250", "25", "450")), annual_pay_cycles=26),
        LineVocabulary("BASE", "regular", "VARIABLE", "variable", "CORRECTION", "correction"),
        DeductionVocabulary("TAX", "tax", "BENEFITS", "benefit"), Decimal("0"), Decimal("160"),
    )
    config = replace(config, configuration_sha256=hashlib.sha256(_json_bytes(config)).hexdigest())
    require_seed_contract(config)
    return config


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    if type(value) is int:
        return str(value)
    if isinstance(value, Decimal) and value.is_finite():
        return format(value, ".2f")
    if type(value) is date:
        return "DATE '" + value.isoformat() + "'"
    if type(value) is str and "\x00" not in value:
        return "E'" + value.replace("\\", "\\\\").replace("'", "''").replace("\r", "\\r").replace("\n", "\\n") + "'"
    raise FixtureInvariantError("Unsupported fixture SQL literal type.")


def fixture_dump_bytes(fixture: GeneratedFixture, config: SeedConfiguration | None = None) -> bytes:
    """Deterministic data-only INSERT snapshot. No DROP/TRUNCATE/CASCADE or ACLs.

    Restore requires the separately installed frozen schema and an empty target.
    Identity restarts use transactional ALTER SEQUENCE, not non-rollback setval.
    """
    config = default_seed_configuration() if config is None else config
    if fixture.configuration_sha256 != config.configuration_sha256:
        raise FixtureInvariantError("Fixture and seed configuration fingerprints differ.")
    require_invariants(fixture, config)
    lines = ["-- STARK R02 synthetic fixture; not a recovered historical dataset.",
             "-- Data only. Apply only to an independently authorized empty fixture database.",
             "BEGIN;", "SET LOCAL search_path TO pg_catalog, public;",
             "SET CONSTRAINTS public.employees_manager_fk DEFERRED;"]
    for table, columns in TABLE_COLUMNS.items():
        for row in sorted(fixture.table(table), key=lambda row: row[TABLE_PRIMARY_KEYS[table]]):
            lines.append(f'INSERT INTO public."{table}" (' + ", ".join('"' + column + '"' for column in columns)
                         + ") VALUES (" + ", ".join(_sql_literal(row[column]) for column in columns) + ");")
    # Sequence names are discovered, not guessed. ALTER RESTART is transactional.
    lines.extend(["DO $stark_r02$", "DECLARE item record; seq text; parts text[];", "BEGIN",
                  "  FOR item IN SELECT * FROM (VALUES"])
    values = []
    for table, key in TABLE_PRIMARY_KEYS.items():
        maximum = max(row[key] for row in fixture.table(table))
        values.append(f"    ('{table}', '{key}', {maximum + 1})")
    lines.append(",\n".join(values))
    lines.extend(["  ) AS v(table_name, column_name, next_id) LOOP",
                  "    seq := pg_catalog.pg_get_serial_sequence('public.' || item.table_name, item.column_name);",
                  "    IF seq IS NULL THEN RAISE EXCEPTION 'Missing fixture identity sequence'; END IF;",
                  "    parts := pg_catalog.parse_ident(seq);",
                  "    IF array_length(parts, 1) <> 2 OR parts[1] <> 'public' THEN RAISE EXCEPTION 'Unexpected fixture sequence'; END IF;",
                  "    EXECUTE pg_catalog.format('ALTER SEQUENCE %I.%I RESTART WITH %s', parts[1], parts[2], item.next_id);",
                  "  END LOOP;", "END;", "$stark_r02$;", "SET CONSTRAINTS ALL IMMEDIATE;", "COMMIT;"])
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_artifact(path: Path, payload: bytes, filename: str) -> None:
    target = Path(path).absolute()
    if target.name != filename or target.is_symlink() or target.resolve().name != filename:
        raise FixtureInvariantError("Artifact output must use its dedicated filename and cannot be a symlink.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".stark-r02-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_fixture_dump(path: Path, fixture: GeneratedFixture, config: SeedConfiguration | None = None) -> str:
    payload = fixture_dump_bytes(fixture, config)
    _write_artifact(path, payload, "fixture_pg_dump.sql")
    return hashlib.sha256(payload).hexdigest()


def planted_fact_observations(fixture: GeneratedFixture) -> Mapping[str, Any]:
    """Observed from generated rows; not historical or live-query evidence."""
    runs = {row["run_number"]: row for row in fixture.table("payroll_runs")}
    year_ids = {row["payroll_run_id"] for row in runs.values() if row["pay_date"].year == 2026}
    taxes: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
    for row in fixture.table("payroll_results"):
        if row["payroll_run_id"] in year_ids:
            taxes[row["employee_id"]] += row["tax_amount"]
    current_comp = {row["employee_id"] for row in fixture.table("employee_compensation")
                    if row["effective_date"] <= FIXTURE_DATE and (row["effective_to"] is None or FIXTURE_DATE < row["effective_to"])}
    departments = {row["department_id"]: 0 for row in fixture.table("departments")}
    for row in fixture.table("employees"):
        if is_active(row) and row["employee_id"] in current_comp:
            departments[row["department_id"]] += 1
    mismatch = runs["PR-2026-012"]
    mismatch_column, mismatch_amount = next(
        (header, mismatch[header] - sum(row[detail] for row in fixture.table("payroll_results")
                                       if row["payroll_run_id"] == mismatch["payroll_run_id"]))
        for header, detail in HEADER_DETAIL_COLUMNS.items()
        if mismatch[header] != sum(row[detail] for row in fixture.table("payroll_results")
                                    if row["payroll_run_id"] == mismatch["payroll_run_id"]))
    correction = runs["PR-2026-024"]
    correction_results = {row["payroll_result_id"] for row in fixture.table("payroll_results")
                          if row["payroll_run_id"] == correction["payroll_run_id"]}
    return {
        "negative_net_run": "PR-2026-006",
        "negative_net_count": sum(row["net_pay"] < 0 for row in fixture.table("payroll_results")
                                  if row["payroll_run_id"] == runs["PR-2026-006"]["payroll_run_id"]),
        "zero_tax_2026_payees": sorted(employee for employee, tax in taxes.items() if tax == 0),
        "header_mismatch_run": "PR-2026-012", "header_mismatch_column": mismatch_column,
        "header_mismatch_usd": str(mismatch_amount),
        "off_cycle_run": "PR-2026-024", "off_cycle_status": correction["status"],
        "off_cycle_correction_count": sum(row["payroll_result_id"] in correction_results for row in fixture.table("payroll_earnings")),
        "small_department_ids": sorted(department for department, count in departments.items() if count < 5),
        "active_employees": sum(is_active(row) for row in fixture.table("employees")),
        "hr_open_scopes": {str(p): sorted(a["division_id"] for a in fixture.table("hr_bp_assignments")
                                          if a["employee_id"] == p and a["effective_to"] is None) for p in (47, 361, 364)},
    }


def write_fixture_manifest(path: Path, dump_path: Path, fixture: GeneratedFixture,
                           config: SeedConfiguration | None = None) -> Mapping[str, Any]:
    config = default_seed_configuration() if config is None else config
    checks = require_invariants(fixture, config)
    payload = Path(dump_path).read_bytes()
    if payload != fixture_dump_bytes(fixture, config):
        raise FixtureInvariantError("Dump bytes differ from the generated fixture; manifest not written.")
    digest = hashlib.sha256(payload).hexdigest()
    root = Path(__file__).resolve().parent
    manifest = {
        "fixture_version": FIXTURE_VERSION, "fixture_date": FIXTURE_DATE.isoformat(), "fixture_seed": FIXTURE_SEED,
        "fixture_dump_sha256": digest, "sha256": digest,
        "row_counts": {table: len(fixture.table(table)) for table in TABLE_COLUMNS},
        "planted_facts": planted_fact_observations(fixture),
        "invariants": [_json_value(check) for check in checks],
        "verification": {"scope": "offline_generated_rows", "live_postgresql_verified": False,
                         "historical_dataset_fidelity_verified": False, "historical_schema_fidelity_verified": False,
                         "original_historical_invariant_list_recovered": False},
        "provenance": {"baseline": "new R02 synthetic baseline authorized from Antigravity R02 design review",
                       "configuration_sha256": fixture.configuration_sha256,
                       "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "schema_sha256": hashlib.sha256((root / "schema.sql").read_bytes()).hexdigest(),
                       "faker_version": importlib.metadata.version("Faker"), "faker_locale": "en_US",
                       "python_version": sys.version.split()[0], "random_seed": FIXTURE_SEED},
    }
    _write_artifact(path, _json_bytes(manifest), "fixture_manifest.json")
    return manifest


class ResetSafetyError(ValueError):
    """No destructive SQL is permitted without verified isolated ownership."""


def require_test_database_name(name: str) -> None:
    if (type(name) is not str or "prod" in name.lower() or name.lower() in {"postgres", "template0", "template1"}
            or re.fullmatch(r"stark_t2sql(?:_test(?:_[a-z0-9]+)*)?", name) is None):
        raise ResetSafetyError("Reset requires an explicitly named isolated STARK test database; critical/prod names are forbidden.")


@dataclass(frozen=True, slots=True)
class IsolationProof:
    """Real owner input, not generated here or inferred from a database name.

    Provision separately: database connection limit 1; COMMENT ON DATABASE JSON
    with kind=stark_t2sql_isolated_fixture, version=1, database_oid,
    isolation_token and schema_sha256. The token must match this private local
    authorization file. OID/endpoint/hash must describe the actual test clone.
    """

    database_name: str
    database_oid: int
    server_address: str
    server_port: int
    isolation_token: str = field(repr=False)
    schema_sha256: str

    def __post_init__(self) -> None:
        require_test_database_name(self.database_name)
        if type(self.database_oid) is not int or self.database_oid <= 0:
            raise ResetSafetyError("Actual isolated database OID is required.")
        if not ipaddress.ip_address(self.server_address).is_loopback:
            raise ResetSafetyError("Only numeric loopback database endpoints are allowed.")
        if type(self.server_port) is not int or not 1 <= self.server_port <= 65535:
            raise ResetSafetyError("Actual isolated database port is required.")
        if type(self.isolation_token) is not str or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", self.isolation_token) is None:
            raise ResetSafetyError("Actual owner isolation token is required.")
        if type(self.schema_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.schema_sha256) is None:
            raise ResetSafetyError("Actual frozen schema SHA-256 is required.")

    @classmethod
    def from_file(cls, path: Path) -> IsolationProof:
        with Path(path).open("rb") as source:
            payload = source.read(65537)
        if len(payload) > 65536:
            raise ResetSafetyError("Isolation proof exceeds its size bound.")
        return cls(**json.loads(payload))


def _verify_database_identity(cursor: Any, proof: IsolationProof) -> None:
    cursor.execute("SELECT d.datname, d.oid, pg_catalog.inet_server_addr()::text, pg_catalog.inet_server_port(), "
                   "pg_catalog.shobj_description(d.oid, 'pg_database'), d.datconnlimit, "
                   "d.datdba = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user) "
                   "FROM pg_catalog.pg_database d WHERE d.datname = pg_catalog.current_database()")
    row = cursor.fetchone()
    if row is None:
        raise ResetSafetyError("Actual database identity is unavailable.")
    name, oid, address, port, comment, connection_limit, owns_database = row
    expected = {"kind": "stark_t2sql_isolated_fixture", "version": 1, "database_oid": proof.database_oid,
                "isolation_token": proof.isolation_token, "schema_sha256": proof.schema_sha256}
    try:
        marker = json.loads(comment)
    except (ValueError, TypeError) as exc:
        raise ResetSafetyError("Database has no independently provisioned isolation marker.") from exc
    if ((name, oid, address, port) != (proof.database_name, proof.database_oid, proof.server_address, proof.server_port)
            or marker != expected or connection_limit != 1 or owns_database is not True):
        raise ResetSafetyError("Database identity, owner, single-client limit or marker differs from authorization.")
    cursor.execute("SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE datid = %s "
                   "AND pid <> pg_catalog.pg_backend_pid() AND backend_type = 'client backend'", (oid,))
    if cursor.fetchone()[0] != 0:
        raise ResetSafetyError("The isolated fixture database has other active clients.")


def _verify_isolated_schema(cursor: Any, root: Path) -> None:
    """Audit before truncation. Refuse extras, inheritance and executable hooks."""
    cursor.execute("SELECT n.nspname, c.relname, c.relkind, c.relispartition FROM pg_catalog.pg_class c "
                   "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
                   "AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%' "
                   "AND c.relkind IN ('r','p','v','m','f') ORDER BY n.nspname,c.relname")
    if set(cursor.fetchall()) != {("public", table, "r", False) for table in TABLE_COLUMNS}:
        raise ResetSafetyError("Database must contain only the twelve ordinary fixture tables; unrelated objects are forbidden.")
    _require_database_shape(cursor)
    source = re.sub(r"--[^\n]*", "", (root / "schema.sql").read_text(encoding="utf-8"))
    expected = []
    constraints = set()
    for table, body in re.findall(r"CREATE TABLE public\.([a-z_]+)\s*\((.*?)\n\);", source, re.S):
        for column, datatype, tail in re.findall(r"^\s+([a-z_]+) (INTEGER|TEXT|VARCHAR\(\d+\)|NUMERIC\(\d+,\d+\)|DATE|BOOLEAN)([^\n]*)", body, re.M):
            formatted = datatype.lower().replace("varchar", "character varying")
            expected.append((table, column, formatted, "NOT NULL" in tail or column == TABLE_PRIMARY_KEYS[table],
                             "d" if "AS IDENTITY" in tail else ""))
        for name, kind in re.findall(r"CONSTRAINT ([a-z_]+)\s+(PRIMARY KEY|UNIQUE|CHECK|FOREIGN KEY)", body):
            constraints.add((table, name, {"PRIMARY KEY": "p", "UNIQUE": "u", "CHECK": "c", "FOREIGN KEY": "f"}[kind]))
    cursor.execute("SELECT c.relname,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity "
                   "FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid "
                   "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum")
    if set(cursor.fetchall()) != set(expected):
        raise ResetSafetyError("Live column types/nullability/identities do not match frozen schema.sql.")
    cursor.execute("SELECT c.relname,k.conname,k.contype,k.convalidated FROM pg_catalog.pg_constraint k "
                   "JOIN pg_catalog.pg_class c ON c.oid=k.conrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE n.nspname='public'")
    live_constraints = cursor.fetchall()
    if {(t, name, kind) for t, name, kind, valid in live_constraints if valid} != constraints or any(not row[3] for row in live_constraints):
        raise ResetSafetyError("Live constraint inventory differs from frozen schema.sql.")
    expected_keys = set()
    for table, body in re.findall(r"CREATE TABLE public\.([a-z_]+)\s*\((.*?)\n\);", source, re.S):
        for match in re.finditer(r"CONSTRAINT ([a-z_]+)\s+(PRIMARY KEY|UNIQUE|FOREIGN KEY)\s*\(([^)]+)\)(.*?)(?=,\s*CONSTRAINT|\Z)", body, re.S):
            name, kind, columns, tail = match.groups()
            reference = re.search(r"REFERENCES public\.([a-z_]+)\s*\(([^)]+)\)", tail) if kind == "FOREIGN KEY" else None
            expected_keys.add((table, name, tuple(c.strip() for c in columns.split(",")),
                               "public" if reference else None, reference[1] if reference else None,
                               tuple(c.strip() for c in reference[2].split(",")) if reference else (),
                               "DEFERRABLE" in tail and "NOT DEFERRABLE" not in tail, False,
                               "a" if reference else None, "r" if reference else None))
    cursor.execute("SELECT c.relname,k.conname, "
                   "ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY x(num,ord) "
                   "JOIN pg_catalog.pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=x.num ORDER BY x.ord), "
                   "rn.nspname,rc.relname, "
                   "ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY x(num,ord) "
                   "JOIN pg_catalog.pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=x.num ORDER BY x.ord), "
                   "k.condeferrable,k.condeferred, "
                   "CASE WHEN k.contype='f' THEN k.confupdtype::text END, "
                   "CASE WHEN k.contype='f' THEN k.confdeltype::text END "
                   "FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid "
                   "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                   "LEFT JOIN pg_catalog.pg_class rc ON rc.oid=k.confrelid "
                   "LEFT JOIN pg_catalog.pg_namespace rn ON rn.oid=rc.relnamespace "
                   "WHERE n.nspname='public' AND k.contype IN ('p','u','f')")
    live_keys = {(t, name, tuple(cols), ns, target, tuple(refs), deferred, initially, update, delete)
                 for t, name, cols, ns, target, refs, deferred, initially, update, delete in cursor.fetchall()}
    if live_keys != expected_keys:
        raise ResetSafetyError("Live primary/unique/foreign keys or deferral/actions differ from schema.sql.")
    cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_inherits), "
                   "EXISTS (SELECT 1 FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                   "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal), "
                   "EXISTS (SELECT 1 FROM pg_catalog.pg_rewrite r JOIN pg_catalog.pg_class c ON c.oid=r.ev_class "
                   "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'), "
                   "EXISTS (SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                   "WHERE n.nspname NOT IN ('pg_catalog','information_schema'))")
    if any(cursor.fetchone()):
        raise ResetSafetyError("Inheritance, user triggers/rules or custom routines are forbidden in a reset target.")
    # Reject foreign keys into the fixture from anywhere; RESTRICT provides a
    # second, database-enforced stop even if catalog state changes unexpectedly.
    cursor.execute("SELECT sn.nspname,s.relname,tn.nspname,t.relname FROM pg_catalog.pg_constraint k "
                   "JOIN pg_catalog.pg_class s ON s.oid=k.conrelid JOIN pg_catalog.pg_namespace sn ON sn.oid=s.relnamespace "
                   "JOIN pg_catalog.pg_class t ON t.oid=k.confrelid JOIN pg_catalog.pg_namespace tn ON tn.oid=t.relnamespace "
                   "WHERE k.contype='f' AND tn.nspname='public' AND t.relname=ANY(%s)", (list(TABLE_COLUMNS),))
    if any(sn != "public" or tn != "public" or s not in TABLE_COLUMNS or t not in TABLE_COLUMNS for sn,s,tn,t in cursor.fetchall()):
        raise ResetSafetyError("Foreign keys outside the fixture reset set are forbidden.")


def _read_fixture(cursor: Any, configuration: SeedConfiguration) -> GeneratedFixture:
    from psycopg2 import sql
    data = {}
    for table, columns in TABLE_COLUMNS.items():
        cursor.execute(sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
            sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            sql.Identifier("public", table), sql.Identifier(TABLE_PRIMARY_KEYS[table])))
        data[table] = tuple(MappingProxyType(dict(zip(columns, row))) for row in cursor.fetchall())
    return GeneratedFixture(MappingProxyType(data), configuration.configuration_sha256, configuration.fidelity)


def create_fixture(configuration_path: Path | None = None, *, project_root: Path | None = None,
                   admin_source: Any, reset: bool = False, authorization: IsolationProof | None = None,
                   database_name: str | None = None) -> FixtureCreationSummary:
    """Atomic scoped load/reset; no database creation, marker creation or CASCADE.

    All catalog/isolation guards precede the first destructive statement. The
    18 checks and exact row comparison run before commit, then on a fresh read.
    PostgreSQL sequence RESTART is transactional, unlike setval.
    """
    from stark_t2sql.db.connections import AdminConnectionSource
    if type(admin_source) is not AdminConnectionSource:
        raise MissingSeedInputError("Fixture loading requires the explicit trusted administrative source.")
    if type(reset) is not bool or type(authorization) is not IsolationProof:
        raise ResetSafetyError("A real isolated-test database authorization is mandatory.")
    require_test_database_name(database_name)
    credentials = admin_source.alias.load_credentials()
    if (credentials.database != database_name or authorization.database_name != database_name
            or (credentials.host, credentials.port) != (authorization.server_address, authorization.server_port)):
        raise ResetSafetyError("Configured database/endpoint differs from explicit authorization.")
    root = Path(__file__).resolve().parent if project_root is None else project_root.resolve()
    if admin_source.config.paths.root.resolve() != root:
        raise ResetSafetyError("Administrative source and fixture workspace differ.")
    if hashlib.sha256((root / "schema.sql").read_bytes()).hexdigest() != authorization.schema_sha256:
        raise ResetSafetyError("Isolation proof does not bind the current frozen schema.sql.")
    config = default_seed_configuration() if configuration_path is None else load_seed_configuration(configuration_path, project_root=root)
    fixture = generate_fixture(config)
    from psycopg2 import sql
    with admin_source.connection(readonly=False) as connection:
        with connection.cursor() as cursor:
            _verify_database_identity(cursor, authorization)
            cursor.execute("SET LOCAL search_path TO pg_catalog, public")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            tables = sql.SQL(", ").join(sql.SQL("ONLY {}").format(sql.Identifier("public", table)) for table in TABLE_COLUMNS)
            cursor.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(tables))
            _verify_isolated_schema(cursor, root)
            sequences = {}
            for table, key in TABLE_PRIMARY_KEYS.items():
                cursor.execute("SELECT n.nspname,c.relname FROM pg_catalog.pg_class c "
                               "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                               "JOIN pg_catalog.pg_depend d ON d.objid=c.oid AND d.classid='pg_catalog.pg_class'::regclass "
                               "WHERE c.relkind='S' AND c.oid=pg_catalog.pg_get_serial_sequence(%s,%s)::regclass "
                               "AND d.refobjid=%s::regclass AND d.deptype IN ('a','i') "
                               "AND d.refobjsubid=(SELECT attnum FROM pg_catalog.pg_attribute WHERE attrelid=%s::regclass AND attname=%s)",
                               ("public." + table, key, "public." + table, "public." + table, key))
                sequence = cursor.fetchone()
                if sequence is None or sequence[0] != "public" or tuple(sequence) in sequences.values():
                    raise ResetSafetyError("Identity sequence is not uniquely owned by its fixture key.")
                sequences[table] = tuple(sequence)
            if reset:
                # Do not restart every possibly-owned sequence implicitly.
                # Only the 12 individually verified key sequences change below.
                cursor.execute(sql.SQL("TRUNCATE TABLE {} CONTINUE IDENTITY RESTRICT").format(tables))
            else:
                for table in TABLE_COLUMNS:
                    cursor.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(sql.Identifier("public", table)))
                    if cursor.fetchone()[0]:
                        raise ResetSafetyError("Non-empty fixture requires explicit --reset.")
            cursor.execute("SET CONSTRAINTS public.employees_manager_fk DEFERRED")
            for table, columns in TABLE_COLUMNS.items():
                statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier("public", table), sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns))
                cursor.executemany(statement, [tuple(row[column] for column in columns) for row in fixture.table(table)])
            for table, key in TABLE_PRIMARY_KEYS.items():
                cursor.execute(sql.SQL("ALTER SEQUENCE {} RESTART WITH {}").format(
                    sql.Identifier(*sequences[table]), sql.Literal(max(row[key] for row in fixture.table(table)) + 1)))
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            observed = _read_fixture(cursor, config)
            require_invariants(observed, config)
            if observed.rows != fixture.rows:
                raise FixtureInvariantError("Database round trip differs from generated rows; transaction rolled back.")
    with admin_source.connection(readonly=True) as connection:
        with connection.cursor() as cursor:
            _verify_database_identity(cursor, authorization)
            checks = require_invariants(_read_fixture(cursor, config), config)
    return FixtureCreationSummary(FIXTURE_VERSION, config.configuration_sha256,
                                  config.fidelity.historical_schema_sha256 if config.fidelity else None,
                                  authorization.schema_sha256,
                                  MappingProxyType({table: len(fixture.table(table)) for table in TABLE_COLUMNS}), checks, True)


def _cli_admin_source(root: Path) -> Any:
    # Direct script execution does not require installing the project package.
    sys.path.insert(0, str(root / "src"))
    from stark_t2sql.config import DatabaseConnectionAlias, load_config
    from stark_t2sql.db.connections import AdminConnectionSource
    from stark_t2sql.utils.local_only import LoopbackEndpoint
    user = os.environ.get("STARK_R02_ADMIN_USER")
    if not user:
        raise ResetSafetyError("Explicit STARK_R02_ADMIN_USER, STARK_R02_DB_NAME and STARK_R02_DB_PASSWORD are required.")
    port = int(os.environ.get("STARK_R02_DB_PORT", "5432"))
    alias = DatabaseConnectionAlias("r02_setup", user, "127.0.0.1", port, "STARK_R02_DB_NAME", "STARK_R02_DB_PASSWORD")
    base = load_config(root)
    config = replace(base, database_connections=base.database_connections + (alias,),
                     allowed_runtime_endpoints=base.allowed_runtime_endpoints + (LoopbackEndpoint("postgresql", "127.0.0.1", port),))
    return AdminConnectionSource(config, "r02_setup")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="In-memory generation/checks only (default).")
    parser.add_argument("--reset", action="store_true", help="Explicit isolated-test database reset; requires proof.")
    parser.add_argument("--database-name")
    parser.add_argument("--isolation-proof", type=Path, help="Actual owner proof matching pre-provisioned database COMMENT.")
    parser.add_argument("--export-dump", type=Path)
    parser.add_argument("--export-manifest", type=Path)
    args = parser.parse_args(argv)
    if args.dry_run and (args.reset or args.export_dump or args.export_manifest):
        parser.error("--dry-run cannot be combined with database or file-write actions.")
    if args.reset and (not args.database_name or args.isolation_proof is None):
        parser.error("--reset requires --database-name and a real --isolation-proof; name alone is insufficient.")
    try:
        if args.reset:
            require_test_database_name(args.database_name)
            proof = IsolationProof.from_file(args.isolation_proof)
            source = _cli_admin_source(Path(__file__).resolve().parent)
            try:
                create_fixture(admin_source=source, reset=True, authorization=proof, database_name=args.database_name)
            finally:
                source.close()
        config = default_seed_configuration()
        fixture = generate_fixture(config)
        checks = require_invariants(fixture, config)
        if args.export_dump:
            if args.export_manifest and args.export_dump.resolve() == args.export_manifest.resolve():
                raise FixtureInvariantError("Dump and manifest paths must be different.")
            write_fixture_dump(args.export_dump, fixture, config)
        if args.export_manifest:
            write_fixture_manifest(args.export_manifest, args.export_dump or Path(__file__).resolve().parent / "fixture_pg_dump.sql", fixture, config)
        print(json.dumps({"fixture_version": FIXTURE_VERSION, "row_counts": {table: len(fixture.table(table)) for table in TABLE_COLUMNS},
                          "operational_invariants_satisfied": sum(check.satisfied for check in checks),
                          "planted_facts": planted_fact_observations(fixture),
                          "database_action": "verified_reset" if args.reset else "none",
                          "historical_dataset_fidelity_verified": False}, sort_keys=True))
        return 0
    except Exception as exc:
        # Do not echo credentials, DSNs, isolation tokens or raw driver text.
        reason = str(exc) if isinstance(exc, (ResetSafetyError, FixtureInvariantError, MissingSeedInputError)) else type(exc).__name__
        print("R02 operation refused or failed: " + reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
