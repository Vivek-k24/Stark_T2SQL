"""Fixture-derived simulated identities (FR-1, FR-6, section 11.2).

Authoring this module does not read a fixture or contact PostgreSQL. The future
startup path must supply the real dump, its manifest digest field, and a governed
Sales division name. These are dependencies, never sample fixture values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import json
from types import MappingProxyType
from typing import TYPE_CHECKING

from stark_t2sql.config import FIXTURE_AS_OF_DATE, ProjectPaths, require_source_file
from stark_t2sql.contracts import Persona
from stark_t2sql.errors import ConfigurationError, InvalidRequestError, SourceReadError
from stark_t2sql.utils.fingerprints import sha256_file

if TYPE_CHECKING:
    from stark_t2sql.db.connections import AdminConnectionSource
    from stark_t2sql.policy.loader import PolicyMatrix


def fixture_digest(paths: ProjectPaths, manifest_hash_path: tuple[str, ...]) -> str:
    """Require the actual dump to match its actual manifest digest.

    The FRD does not define a manifest JSON key spelling. A caller must identify
    its digest field explicitly rather than this module inventing a manifest.
    No fixture content, manifest, or hash is generated here.
    """

    if not manifest_hash_path or any(type(key) is not str or not key for key in manifest_hash_path):
        raise ConfigurationError("The real fixture manifest digest field path is required.")
    manifest_path = require_source_file(paths.fixture_manifest, label="fixture manifest")
    dump_path = require_source_file(paths.fixture_dump, label="authoritative fixture dump")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in manifest_hash_path:
            if not isinstance(value, dict):
                raise KeyError(key)
            value = value[key]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
        raise SourceReadError("The supplied fixture manifest digest field is unavailable.") from exc
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ConfigurationError("The fixture manifest must contain a lowercase SHA-256 digest.")
    actual = sha256_file(dump_path)
    if actual != value:
        raise ConfigurationError("The supplied fixture dump does not match its manifest.")
    return actual


_REGISTRY_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class PersonaRegistry:
    """Four frozen choices established only by the trusted startup resolver.

    Persona instances carry metadata, not authentication. Exact equality to a
    resolved, predefined tuple is required; arbitrary principals are refused.
    The private construction token prevents accidentally treating hand-written
    Persona objects as a fixture-derived registry.
    """

    personas: Mapping[str, Persona]
    fixture_dump_sha256: str
    as_of_date: date
    division_scopes: Mapping[str, tuple[int, ...]]

    def __init__(
        self,
        personas: Mapping[str, Persona],
        fixture_dump_sha256: str,
        as_of_date: date,
        division_scopes: Mapping[str, tuple[int, ...]],
        *,
        _token: object,
    ) -> None:
        if _token is not _REGISTRY_TOKEN:
            raise ConfigurationError("Personas must be established by the fixture startup resolver.")
        if set(personas) != {"payroll", "hr_1", "hr_2", "sales"}:
            raise ConfigurationError("Exactly four predefined persona choices are required.")
        object.__setattr__(self, "personas", MappingProxyType(dict(personas)))
        object.__setattr__(self, "fixture_dump_sha256", fixture_dump_sha256)
        object.__setattr__(self, "as_of_date", as_of_date)
        object.__setattr__(self, "division_scopes", MappingProxyType(dict(division_scopes)))

    def resolve(self, selection: str | Persona) -> Persona:
        if type(selection) is str and selection in self.personas:
            return self.personas[selection]
        if type(selection) is Persona:
            for persona in self.personas.values():
                if selection == persona:
                    return persona
        raise InvalidRequestError("The selection is not a predefined fixture-resolved persona.")


def resolve_personas(
    admin_source: AdminConnectionSource,
    matrix: PolicyMatrix,
    *,
    sales_division_name: str,
    fixture_hash_path: tuple[str, ...],
    as_of_date: date = FIXTURE_AS_OF_DATE,
) -> PersonaRegistry:
    """Derive personas using fixed trusted SQL, never a restricted/model path.

    326, 47, 361 and the conditional fallback 364 are the only fixture principal
    constants authorized by the FRD. Missing 47/361 is a startup failure; it is
    not permission to substitute a different employee. A Sales manager must be
    active on the explicit fixture date and have real direct reports. The query
    determines the ID and makes a deterministic choice by actual employee ID.
    This trusted identity query does not expose active_headcount to Sales (I-01).
    """

    # Local imports keep the trusted and generated-SQL capability types separate.
    from stark_t2sql.db.connections import AdminConnectionSource
    from stark_t2sql.db.catalog import snapshot_schema

    if type(admin_source) is not AdminConnectionSource:
        raise ConfigurationError("Persona startup requires the separate trusted administrative source.")
    if type(as_of_date) is not date or as_of_date != FIXTURE_AS_OF_DATE:
        raise ConfigurationError("Persona derivation requires the explicitly supplied fixture date.")
    if type(sales_division_name) is not str or not sales_division_name.strip():
        raise ConfigurationError("A governed fixture Sales division name must be supplied.")
    digest = fixture_digest(admin_source.config.paths, fixture_hash_path)
    with admin_source.connection(readonly=True) as connection:
        # FORCE RLS also applies to ordinary table owners. This separate trusted
        # reference path must establish complete fixture visibility explicitly;
        # runtime and evaluation candidates must never receive this capability.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = current_user"
            )
            administrative_scope = cursor.fetchone()
            if administrative_scope is None or not any(administrative_scope):
                raise ConfigurationError(
                    "Trusted persona reference queries require SUPERUSER or BYPASSRLS; "
                    "ownership alone does not establish complete FORCE RLS fixture visibility."
                )
        # This is a future runtime call: it fails closed if fixture/schema inputs
        # are missing or inconsistent with the supplied policy matrix.
        snapshot = snapshot_schema(connection, schema=matrix.schema)
        from stark_t2sql.policy.loader import require_policy_schema

        require_policy_schema(matrix, snapshot.columns_by_table)
        import psycopg2.sql as sql

        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT employee_id FROM {}.employees WHERE employee_id = ANY(%s) ORDER BY employee_id").format(sql.Identifier(matrix.schema)),
                ([326, 47, 361],),
            )
            present = {row[0] for row in cursor.fetchall()}
            missing = sorted({326, 47, 361} - present)
            if missing:
                raise ConfigurationError("Missing configured fixture principal IDs: " + ", ".join(map(str, missing)))

            def divisions(principal_id: int) -> tuple[int, ...]:
                cursor.execute(
                    sql.SQL("SELECT DISTINCT division_id FROM {}.hr_bp_assignments WHERE employee_id = %s AND effective_to IS NULL ORDER BY division_id").format(sql.Identifier(matrix.schema)),
                    (principal_id,),
                )
                return tuple(row[0] for row in cursor.fetchall())

            first_id = 47
            first_scope = divisions(first_id)
            second_id = 361
            second_scope = divisions(second_id)
            if not first_scope or not second_scope or first_scope == second_scope:
                cursor.execute(
                    sql.SQL("SELECT employee_id FROM {}.employees WHERE employee_id = %s").format(sql.Identifier(matrix.schema)),
                    (364,),
                )
                if cursor.fetchone() is None:
                    raise ConfigurationError("Missing FRD-authorized fallback fixture principal ID: 364")
                fallback_scope = divisions(364)
                if first_scope and fallback_scope and first_scope != fallback_scope:
                    second_id, second_scope = 364, fallback_scope
                elif second_scope and fallback_scope and second_scope != fallback_scope:
                    # Preserve the original 361 scope when 47 lacks a scope.
                    first_id, first_scope = 364, fallback_scope
                else:
                    raise ConfigurationError("Fixture HR principals do not provide two distinct nonempty current division scopes.")
            cursor.execute(
                sql.SQL("SELECT division_id FROM {}.divisions WHERE division_name = %s ORDER BY division_id").format(sql.Identifier(matrix.schema)),
                (sales_division_name,),
            )
            sales_divisions = cursor.fetchall()
            if len(sales_divisions) != 1:
                raise ConfigurationError("The governed Sales division selector does not resolve uniquely in the fixture.")
            sales_division_id = sales_divisions[0][0]
            cursor.execute(
                sql.SQL("""
                    SELECT manager.employee_id
                    FROM {schema}.employees AS manager
                    JOIN {schema}.departments AS department
                      ON department.department_id = manager.department_id
                    WHERE department.division_id = %s
                      AND manager.employment_type IN ('full_time', 'part_time')
                      AND manager.status <> 'cancelled_pre_hire'
                      AND manager.hire_date <= %s
                      AND (manager.termination_date IS NULL OR manager.termination_date > %s)
                      AND EXISTS (SELECT 1 FROM {schema}.employees AS report
                                  WHERE report.manager_id = manager.employee_id)
                    ORDER BY manager.employee_id
                    LIMIT 1
                """).format(schema=sql.Identifier(matrix.schema)),
                (sales_division_id, as_of_date, as_of_date),
            )
            manager = cursor.fetchone()
            if manager is None:
                raise ConfigurationError("No active fixture Sales manager has actual direct reports.")
            sales_id = manager[0]

    def persona(display_name: str, role_name: str, principal_id: int) -> Persona:
        role = matrix.role(role_name)
        return Persona(display_name, role.name, principal_id, role.login_role)

    return PersonaRegistry(
        {
            "payroll": persona("Payroll specialist", "app_payroll", 326),
            "hr_1": persona("HR business partner #1", "app_hr_bp", first_id),
            "hr_2": persona("HR business partner #2", "app_hr_bp", second_id),
            "sales": persona("Sales manager", "app_sales_mgr", sales_id),
        },
        digest,
        as_of_date,
        {"hr_1": first_scope, "hr_2": second_scope},
        _token=_REGISTRY_TOKEN,
    )
