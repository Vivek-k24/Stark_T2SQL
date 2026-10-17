"""Proposed, individually reviewable PostgreSQL function signatures (FR-5.6).

These rules are a DRAFT, not an assertion of completed function review/tests.
ParserReviewApproval in validator.py must explicitly admit each rule after
separate human review and positive/negative contracts on the actual parser.
Recognized parser functions and Anonymous calls take the same default-deny
path. Qualification is deliberately excluded: regeneration uses unqualified
built-ins under the separately audited trusted search_path. No UDF, extension,
configuration, catalog, I/O, privilege, or set-returning call is
approved here. Individually proposed read-clock signatures below preserve
FR-9.6's separation: a reviewed clock expression may be accepted here while
evaluation records FC-WALLCLOCK. They are inactive until actual human review,
and this module never decides whether a query follows the as-of-date contract.

Purity assumes the governed fixture's built-in scalar column types and the
FR-6 trusted-schema/no-CREATE audit. These Python rules cannot audit a database
or prove an installed object's identity. SQL execution and resource limits
remain exclusively at the existing DB boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Mapping


FUNCTION_POLICY_REVISION = "fr5-function-r05-1"


@dataclass(frozen=True, slots=True)
class FunctionRule:
    """A proposed exact parser representation and PostgreSQL call contract."""

    rule_id: str
    sql_name: str
    parser_class: str
    argument_keys: frozenset[str]
    min_arity: int
    max_arity: int
    semantics: str


# No rule is automatically active merely because it appears in this source.
# Different parser representations get separate IDs/evidence, including the
# two possible DATE_TRUNC layouts. A profile admits only observed layouts.
PROPOSED_RULES: tuple[FunctionRule, ...] = (
    FunctionRule("count-known-v1", "count", "Count", frozenset({"this", "expressions", "big_int"}), 1, 1,
        "COUNT(*) / COUNT(value) / COUNT(DISTINCT values): ordinary read-only aggregate; exact Count big_int boolean is PostgreSQL parser metadata, not a SQL argument."),
    FunctionRule("sum-known-v1", "sum", "Sum", frozenset({"this"}), 1, 1,
        "SUM(built-in numeric value), nullable read-only aggregate; database resolves numeric types."),
    FunctionRule("avg-known-v1", "avg", "Avg", frozenset({"this"}), 1, 1,
        "AVG(built-in numeric value), nullable read-only aggregate; database resolves numeric types."),
    FunctionRule("min-known-v1", "min", "Min", frozenset({"this", "expressions"}), 1, 1,
        "MIN(one built-in scalar value), ordinary aggregate; no multi-argument scalar overload."),
    FunctionRule("max-known-v1", "max", "Max", frozenset({"this", "expressions"}), 1, 1,
        "MAX(one built-in scalar value), ordinary aggregate; no multi-argument scalar overload."),
    FunctionRule("lower-known-v1", "lower", "Lower", frozenset({"this"}), 1, 1,
        "LOWER(one built-in text value); no locale/collation or extension arguments."),
    FunctionRule("upper-known-v1", "upper", "Upper", frozenset({"this"}), 1, 1,
        "UPPER(one built-in text value); no locale/collation or extension arguments."),
    FunctionRule("abs-known-v1", "abs", "Abs", frozenset({"this"}), 1, 1,
        "ABS(one built-in numeric value), deterministic scalar."),
    FunctionRule("round-known-v1", "round", "Round", frozenset({"this", "decimals"}), 1, 2,
        "ROUND(numeric[, integer literal -6..6]); bounded precision argument, built-in numeric overload only."),
    FunctionRule("coalesce-known-v1", "coalesce", "Coalesce", frozenset({"this", "expressions"}), 2, 16,
        "COALESCE(2..16 built-in scalar values); pure SQL conditional expression, all children reviewed."),
    FunctionRule("nullif-known-v1", "nullif", "Nullif", frozenset({"this", "expression"}), 2, 2,
        "NULLIF(two built-in scalar values); pure SQL conditional expression, all children reviewed."),
    FunctionRule("date-trunc-known-v1", "date_trunc", "DateTrunc", frozenset({"this", "expression"}), 2, 2,
        "DATE_TRUNC(literal reviewed unit, timestamp/date value); two arguments only, no timezone overload."),
    FunctionRule("timestamp-trunc-known-v1", "date_trunc", "TimestampTrunc", frozenset({"this", "unit"}), 2, 2,
        "Postgres DATE_TRUNC rendering of TimestampTrunc(value, reviewed unit); no timezone/extra arguments."),
    FunctionRule("row-number-known-v1", "row_number", "RowNumber", frozenset(), 0, 0,
        "ROW_NUMBER() only as the direct function of a reviewed OVER window."),
    FunctionRule("rank-known-v1", "rank", "Rank", frozenset(), 0, 0,
        "RANK() only as the direct function of a reviewed OVER window; no hypothetical-set overload."),
    FunctionRule("dense-rank-known-v1", "dense_rank", "DenseRank", frozenset(), 0, 0,
        "DENSE_RANK() only as the direct function of a reviewed OVER window."),
    FunctionRule("percentile-cont-known-v1", "percentile_cont", "PercentileCont", frozenset({"this", "expression"}), 1, 1,
        "PERCENTILE_CONT(single numeric literal 0..1) WITHIN GROUP (ORDER BY one numeric value); no fraction arrays or OVER form."),
    FunctionRule("cast-special-v1", "cast", "Cast", frozenset({"this", "to"}), 2, 2,
        "CAST(value AS approved built-in scalar DataType), no UDT/domain/regclass/extension cast paths."),
    FunctionRule("extract-special-v1", "extract", "Extract", frozenset({"this", "expression"}), 2, 2,
        "EXTRACT(reviewed calendar field FROM built-in temporal value); field is a parser Var/Identifier, never a call."),
    # Proposed read-clock purity basis: bounded public runtime date/time
    # scalars, no writes, config mutation, privilege or application-row access.
    # They are volatile/stable as PostgreSQL defines, rather than deterministic
    # business dates. Live object/signature review and individual contracts
    # remain required; no proposal is review evidence. Optional class names
    # below are resolved with getattr only in a later approved runtime.
    FunctionRule("current-date-known-v1", "current_date", "CurrentDate", frozenset(), 0, 0,
        "CURRENT_DATE keyword, zero arguments: read-only runtime calendar date; evaluation must record FR-9.6 wall-clock use."),
    FunctionRule("current-timestamp-known-v1", "current_timestamp", "CurrentTimestamp", frozenset({"this"}), 0, 1,
        "CURRENT_TIMESTAMP / parser-normalized NOW(), optional literal precision 0..6; read-only transaction clock scalar."),
    FunctionRule("current-time-known-v1", "current_time", "CurrentTime", frozenset({"this"}), 0, 1,
        "CURRENT_TIME keyword, optional literal precision 0..6; read-only runtime time scalar."),
    FunctionRule("localtimestamp-known-v1", "localtimestamp", "Localtimestamp", frozenset({"this"}), 0, 1,
        "LOCALTIMESTAMP keyword layout, optional literal precision 0..6; read-only runtime timestamp scalar."),
    FunctionRule("localtimestamp-camel-known-v1", "localtimestamp", "LocalTimestamp", frozenset({"this"}), 0, 1,
        "Alternative exact LOCALTIMESTAMP parser class layout; individually admit only an observed class, same precision contract."),
    FunctionRule("age-known-v1", "age", "Age", frozenset({"this", "expression"}), 1, 2,
        "AGE(one or two built-in temporal values), read-only bounded interval scalar; one-argument overload reads the current date."),
    FunctionRule("statement-timestamp-known-v1", "statement_timestamp", "StatementTimestamp", frozenset(), 0, 0,
        "STATEMENT_TIMESTAMP(), no arguments: read-only statement-start clock scalar, no configuration or privilege access."),
    FunctionRule("transaction-timestamp-known-v1", "transaction_timestamp", "TransactionTimestamp", frozenset(), 0, 0,
        "TRANSACTION_TIMESTAMP(), no arguments: read-only transaction-start clock scalar."),
    FunctionRule("clock-timestamp-known-v1", "clock_timestamp", "ClockTimestamp", frozenset(), 0, 0,
        "CLOCK_TIMESTAMP(), no arguments: read-only volatile wall-clock scalar, no state mutation or application data access."),
    FunctionRule("timeofday-known-v1", "timeofday", "TimeOfDay", frozenset(), 0, 0,
        "TIMEOFDAY(), no arguments: bounded formatted runtime clock scalar; no catalog/object/application data access."),
    FunctionRule("count-anonymous-v1", "count", "Anonymous", frozenset({"this", "expressions"}), 1, 1,
        "Anonymous COUNT representation, same COUNT contract as count-known-v1."),
    FunctionRule("sum-anonymous-v1", "sum", "Anonymous", frozenset({"this", "expressions"}), 1, 1,
        "Anonymous SUM representation, same built-in numeric aggregate contract."),
    FunctionRule("avg-anonymous-v1", "avg", "Anonymous", frozenset({"this", "expressions"}), 1, 1,
        "Anonymous AVG representation, same built-in numeric aggregate contract."),
    FunctionRule("min-anonymous-v1", "min", "Anonymous", frozenset({"this", "expressions"}), 1, 1,
        "Anonymous MIN representation, one built-in scalar aggregate argument."),
    FunctionRule("max-anonymous-v1", "max", "Anonymous", frozenset({"this", "expressions"}), 1, 1,
        "Anonymous MAX representation, one built-in scalar aggregate argument."),
    FunctionRule("lower-anonymous-v1", "lower", "Anonymous", frozenset({"this", "expressions"}), 1, 1,
        "Anonymous LOWER representation, one built-in text argument."),
    FunctionRule("date-trunc-anonymous-v1", "date_trunc", "Anonymous", frozenset({"this", "expressions"}), 2, 2,
        "Anonymous DATE_TRUNC representation, literal reviewed unit and value, two arguments only."),
    FunctionRule("percentile-cont-anonymous-v1", "percentile_cont", "Anonymous", frozenset({"this", "expressions"}), 1, 1,
        "Anonymous PERCENTILE_CONT representation, same literal/one-order-key WITHIN GROUP contract."),
    FunctionRule("now-anonymous-v1", "now", "Anonymous", frozenset({"this", "expressions"}), 0, 0,
        "Anonymous NOW(), zero arguments: read-only transaction clock; normalized CurrentTimestamp layout needs its own approval."),
    FunctionRule("age-anonymous-v1", "age", "Anonymous", frozenset({"this", "expressions"}), 1, 2,
        "Anonymous AGE(one or two built-in temporal values), same read-only interval/implicit-clock contract."),
    FunctionRule("statement-timestamp-anonymous-v1", "statement_timestamp", "Anonymous", frozenset({"this", "expressions"}), 0, 0,
        "Anonymous STATEMENT_TIMESTAMP(), zero arguments; read-only bounded runtime metadata scalar."),
    FunctionRule("transaction-timestamp-anonymous-v1", "transaction_timestamp", "Anonymous", frozenset({"this", "expressions"}), 0, 0,
        "Anonymous TRANSACTION_TIMESTAMP(), zero arguments; read-only bounded runtime metadata scalar."),
    FunctionRule("clock-timestamp-anonymous-v1", "clock_timestamp", "Anonymous", frozenset({"this", "expressions"}), 0, 0,
        "Anonymous CLOCK_TIMESTAMP(), zero arguments; volatile read-only runtime clock scalar."),
    FunctionRule("timeofday-anonymous-v1", "timeofday", "Anonymous", frozenset({"this", "expressions"}), 0, 0,
        "Anonymous TIMEOFDAY(), zero arguments; bounded runtime date/time text, no other server metadata."),
)

RULES_BY_ID: Mapping[str, FunctionRule] = MappingProxyType({rule.rule_id: rule for rule in PROPOSED_RULES})
_DATE_UNITS = frozenset({"microsecond", "milliseconds", "millisecond", "second", "minute", "hour", "day", "week", "month", "quarter", "year", "decade", "century", "millennium"})
_EXTRACT_FIELDS = frozenset({"year", "quarter", "month", "week", "day", "dow", "isodow", "doy", "isoyear", "hour", "minute", "second", "milliseconds", "microseconds", "epoch", "decade", "century", "millennium"})
_SCALAR_TYPES = frozenset({"BOOLEAN", "TINYINT", "SMALLINT", "INT", "INTEGER", "BIGINT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE", "REAL", "TEXT", "VARCHAR", "CHAR", "DATE", "TIME", "TIMESTAMP", "TIMESTAMPTZ", "INTERVAL"})


class FunctionPolicyViolation(ValueError):
    """Private reason text; the validator maps it to a safe shared reason code."""


def _present(value: object) -> bool:
    return value is not None and value is not False and value != [] and value != ()


class ReviewedFunctionPolicy:
    """Default deny; caller supplies only rule IDs from actual review evidence."""

    def __init__(self, expressions: object, approved_rule_ids: frozenset[str]) -> None:
        self.exp = expressions
        self.rules = tuple(RULES_BY_ID[rule_id] for rule_id in sorted(approved_rule_ids))
        self._classes = {}
        for rule in self.rules:
            cls = getattr(expressions, rule.parser_class, None)
            if not isinstance(cls, type):
                raise FunctionPolicyViolation(f"Reviewed parser representation is unavailable: {rule.parser_class}.")
            self._classes[rule.rule_id] = cls

    def _is(self, node: object, name: str) -> bool:
        cls = getattr(self.exp, name, None)
        return isinstance(cls, type) and type(node) is cls

    def is_special(self, node: object) -> bool:
        return self._is(node, "Cast") or self._is(node, "Extract")

    def has_reviewed_representation(self, node: object) -> bool:
        """Handle only approved exact classes even if Func is not their base."""
        return any(type(node) is cls for cls in self._classes.values())

    def _arguments(self, node: object, rule: FunctionRule) -> tuple[object, ...]:
        args = node.args
        unknown = {key for key, value in args.items() if _present(value)} - rule.argument_keys
        if unknown:
            raise FunctionPolicyViolation("Unreviewed function arguments/flags are present.")
        if "big_int" in args and not (
            rule.parser_class == "Count" and rule.sql_name == "count" and type(args["big_int"]) is bool
        ):
            raise FunctionPolicyViolation("Only an exact COUNT boolean metadata flag is reviewed.")
        if "expressions" in args and args["expressions"] is not None and not isinstance(args["expressions"], list):
            raise FunctionPolicyViolation("Function arguments use an unreviewed representation.")
        if rule.parser_class == "Anonymous":
            if not isinstance(args.get("this"), str) or args["this"].lower() != rule.sql_name:
                raise FunctionPolicyViolation("Anonymous name does not match its reviewed built-in signature.")
            values = args.get("expressions") or []
            if not isinstance(values, list):
                raise FunctionPolicyViolation("Anonymous arguments use an unreviewed representation.")
            return tuple(values)
        if rule.sql_name in {"row_number", "rank", "dense_rank"}:
            return ()
        if rule.sql_name == "date_trunc":
            if rule.parser_class == "TimestampTrunc":
                return (args.get("unit"), args.get("this"))
            return (args.get("this"), args.get("expression"))
        if rule.sql_name in {"cast", "extract", "nullif"}:
            second = "to" if rule.sql_name == "cast" else "expression"
            return (args.get("this"), args.get(second))
        if rule.sql_name == "age":
            return tuple(args[key] for key in ("this", "expression") if args.get(key) is not None)
        values = []
        if args.get("this") is not None:
            values.append(args["this"])
        additional = args.get("expressions") or []
        if not isinstance(additional, list):
            raise FunctionPolicyViolation("Function arguments use an unreviewed representation.")
        values.extend(additional)
        if args.get("decimals") is not None:
            values.append(args["decimals"])
        if _present(args.get("expression")):
            # PercentileCont's optional expression is not the WITHIN GROUP
            # ordering representation admitted here. It must remain absent.
            raise FunctionPolicyViolation("An additional function expression is unreviewed.")
        return tuple(values)

    def _literal_number(self, node: object) -> Decimal | None:
        sign = Decimal(1)
        if self._is(node, "Neg"):
            sign = Decimal(-1)
            node = node.args.get("this")
        if not self._is(node, "Literal") or node.args.get("is_string") is not False:
            return None
        try:
            value = sign * Decimal(str(node.args.get("this")))
        except (InvalidOperation, ValueError, TypeError):
            return None
        return value if value.is_finite() else None

    def _unit(self, node: object, *, literal_only: bool) -> str | None:
        if self._is(node, "Literal") and node.args.get("is_string") is True:
            text = node.args.get("this")
        elif not literal_only and (self._is(node, "Var") or self._is(node, "Identifier")):
            text = node.args.get("this")
        else:
            return None
        return text.lower() if isinstance(text, str) else None

    def require_scalar_type(self, node: object) -> None:
        if not self._is(node, "DataType"):
            raise FunctionPolicyViolation("CAST requires a reviewed built-in scalar data type.")
        raw_type = node.args.get("this")
        type_name = getattr(raw_type, "name", None)
        if type_name not in _SCALAR_TYPES:
            raise FunctionPolicyViolation("UDT/domain/catalog/collection cast types are not admitted.")
        if any(_present(node.args.get(key)) for key in ("nested", "values", "kind", "prefix")):
            raise FunctionPolicyViolation("An unreviewed data-type modifier is present.")
        parameters = node.args.get("expressions") or []
        if len(parameters) > 2:
            raise FunctionPolicyViolation("Unsupported scalar type parameters.")
        if parameters and type_name not in {"DECIMAL", "NUMERIC", "VARCHAR", "CHAR", "TIME", "TIMESTAMP", "TIMESTAMPTZ"}:
            raise FunctionPolicyViolation("This scalar type admits no parameters in the reviewed profile.")
        for parameter in parameters:
            literal = parameter.args.get("this") if self._is(parameter, "DataTypeParam") else parameter
            number = self._literal_number(literal)
            if number is None or number != number.to_integral_value() or number < 0 or number > 1000:
                raise FunctionPolicyViolation("Scalar type parameters must be reviewed integer literals.")

    def require(self, node: object) -> FunctionRule:
        matches = [rule for rule in self.rules if type(node) is self._classes[rule.rule_id]]
        if self._is(node, "Anonymous"):
            name = node.args.get("this")
            matches = [rule for rule in matches if isinstance(name, str) and name.lower() == rule.sql_name]
        if len(matches) != 1:
            raise FunctionPolicyViolation("Executable function has no unique reviewed signature.")
        rule = matches[0]
        arguments = self._arguments(node, rule)
        if not rule.min_arity <= len(arguments) <= rule.max_arity or any(value is None for value in arguments):
            raise FunctionPolicyViolation("Function arity does not match its reviewed signature.")
        if any(not isinstance(value, self.exp.Expression) for value in arguments):
            raise FunctionPolicyViolation("Function values must use actual expression nodes.")
        parent = getattr(node, "parent", None)
        if self._is(parent, "Dot"):
            raise FunctionPolicyViolation("Qualified executable calls are excluded from this profile.")
        if rule.sql_name != "count" and any(self._is(value, "Distinct") or self._is(value, "Star") for value in arguments):
            raise FunctionPolicyViolation("This function's DISTINCT/star overload is unreviewed.")
        if rule.sql_name == "count":
            value = arguments[0]
            if self._is(value, "Distinct"):
                distinct_values = value.args.get("expressions")
                if not isinstance(distinct_values, list) or not distinct_values or any(
                    not isinstance(item, self.exp.Expression) or self._is(item, "Star") for item in distinct_values
                ):
                    raise FunctionPolicyViolation("COUNT DISTINCT requires concrete values.")
            elif self._is(value, "Star") and any(_present(item) for item in value.args.values()):
                raise FunctionPolicyViolation("Modified COUNT stars are not admitted.")
        if rule.sql_name == "round" and len(arguments) == 2:
            precision = self._literal_number(arguments[1])
            if precision is None or precision != precision.to_integral_value() or not -6 <= precision <= 6:
                raise FunctionPolicyViolation("ROUND precision must be an integer literal from -6 to 6.")
        if rule.sql_name in {"current_timestamp", "current_time", "localtimestamp"} and arguments:
            precision = self._literal_number(arguments[0])
            if precision is None or precision != precision.to_integral_value() or not 0 <= precision <= 6:
                raise FunctionPolicyViolation("Clock precision must be an integer literal from 0 to 6.")
        if rule.sql_name == "date_trunc":
            literal_only = rule.parser_class != "TimestampTrunc"
            if self._unit(arguments[0], literal_only=literal_only) not in _DATE_UNITS:
                raise FunctionPolicyViolation("DATE_TRUNC unit/overload is not reviewed.")
        if rule.sql_name == "extract" and self._unit(arguments[0], literal_only=False) not in _EXTRACT_FIELDS:
            raise FunctionPolicyViolation("EXTRACT field is not reviewed.")
        if rule.sql_name == "cast":
            self.require_scalar_type(arguments[1])
        if rule.sql_name in {"row_number", "rank", "dense_rank"}:
            if not self._is(parent, "Window") or parent.args.get("this") is not node:
                raise FunctionPolicyViolation("This ranking signature requires a direct OVER window.")
        if rule.sql_name == "percentile_cont":
            fraction = self._literal_number(arguments[0])
            if fraction is None or not 0 <= fraction <= 1:
                raise FunctionPolicyViolation("PERCENTILE_CONT requires one literal fraction from 0 to 1.")
            if not self._is(parent, "WithinGroup") or parent.args.get("this") is not node:
                raise FunctionPolicyViolation("PERCENTILE_CONT requires the reviewed WITHIN GROUP form.")
            order = parent.args.get("expression")
            if not self._is(order, "Order") or len(order.args.get("expressions") or []) != 1:
                raise FunctionPolicyViolation("PERCENTILE_CONT requires exactly one ordered value.")
            current = parent
            while current is not None:
                if self._is(current, "Window"):
                    raise FunctionPolicyViolation("PERCENTILE_CONT OVER is not a reviewed PostgreSQL signature.")
                current = getattr(current, "parent", None)
        return rule
