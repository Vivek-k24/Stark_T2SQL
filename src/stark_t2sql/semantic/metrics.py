"""Canonical metric/relationship/date contracts, with no query execution.

Only trusted catalog fragments are compiled. Callers supply an explicit Python
date; there is no wall-clock or fixture-date default. Compilation describes a
measure, grain, filters, aggregation, NULL rules and approved joins to the later
prompt builder. It does not assemble or submit an executable SELECT statement.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import re

from ..db.catalog import SchemaSnapshot
from ..errors import ConfigurationError, InvalidRequestError
from ..policy.loader import PolicyMatrix
from .contracts import MetricContract
from .entitlements import metric_is_allowed
from .models import SemanticCatalog


_PARAMETER = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z_0-9]*)(?![a-zA-Z_0-9])")
_CAST_AS_OF_PARAMETER = re.compile(r"CAST\s*\(\s*:as_of_date\s+AS\s+DATE\s*\)", re.IGNORECASE)
_AS_OF_PARAMETER = re.compile(r"(?<!:):as_of_date(?![a-zA-Z_0-9])")
# A missing argument must raise the same typed request error as None/datetime.
# This sentinel supplies no date and cannot be used as a runtime default.
_MISSING_DATE = object()


def _require_date(as_of_date: date) -> date:
    if type(as_of_date) is not date:
        raise InvalidRequestError("Canonical semantics require an explicit date, without a timestamp.")
    return as_of_date


def _bind_date(fragment: str, as_of_date: date) -> str:
    _require_date(as_of_date)
    parameters = set(_PARAMETER.findall(fragment))
    if parameters - {"as_of_date"}:
        raise ConfigurationError("A governed fragment has an unsupported runtime parameter.")
    # The value originates only from a typed date, never user SQL or text.
    date_literal = "DATE '" + as_of_date.isoformat() + "'"
    bound = _CAST_AS_OF_PARAMETER.sub(date_literal, fragment)
    bound = _AS_OF_PARAMETER.sub(date_literal, bound)
    if ":as_of_date" in bound.casefold():
        raise ConfigurationError("A governed date parameter could not be completely bound.")
    return bound


def compile_metric(
    metric_id: str,
    catalog: SemanticCatalog,
    matrix: PolicyMatrix,
    snapshot: SchemaSnapshot,
    business_role: str,
    as_of_date: date = _MISSING_DATE,
) -> MetricContract:
    """Return the role-eligible canonical meaning at an explicit business date.

    Catalog load-time contracts own canonical definitions. For active headcount,
    these include DISTINCT employee_id, full/part-time eligibility, exclusion of
    cancelled_pre_hire, hire <= date and termination NULL or strictly > date.
    Posted/closed payroll is a union of status values, not an impossible AND on
    one status field. Compensation intervals use [effective_date, effective_to)
    and bonus_target_pct is percentage points on annual base_salary. No caller
    may silently replace those rules with visible-row count, SUM/AVG percentage,
    pay_period_end or a current-time predicate.
    """
    _require_date(as_of_date)
    if not isinstance(metric_id, str) or metric_id not in catalog.metrics:
        raise ConfigurationError("The requested governed metric is not defined.")
    if not metric_is_allowed(catalog, matrix, snapshot, business_role, metric_id):
        raise ConfigurationError("The requested governed metric is unavailable for this role.")
    metric = catalog.metrics[metric_id]
    temporal_rules = tuple(
        replace(
            catalog.temporal_rules[rule_id],
            predicate=_bind_date(catalog.temporal_rules[rule_id].predicate, as_of_date),
            selection=_bind_date(catalog.temporal_rules[rule_id].selection, as_of_date),
        )
        for rule_id in sorted(metric.temporal_rule_ids)
    )
    return MetricContract(
        metric_id=metric.id,
        expression=_bind_date(metric.expression, as_of_date),
        grain=metric.grain,
        filters=tuple(_bind_date(item, as_of_date) for item in metric.filters),
        relationships=tuple(catalog.relationships[item] for item in sorted(metric.relationship_ids)),
        aggregation=metric.aggregation,
        null_handling=metric.null_handling,
        units=metric.units,
        temporal_rules=temporal_rules,
        as_of_date=as_of_date,
    )
