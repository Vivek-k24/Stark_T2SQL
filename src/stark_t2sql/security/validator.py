"""Draft fail-closed FR-5 PostgreSQL SELECT-family review, without execution.

Acceptance is conditional on an externally supplied human review profile for
the actual sqlglot release, exact AST layouts, and individually reviewed
function rules. This source is neither that evidence nor acceptance A/B/C.
The user's NFR-6 exception permits drafting only. No parser is imported or
candidate reviewed on module import, and no database client is used here.

The admitted grammar describes SELECT/CTE/set queries, boolean operators,
CASE/EXISTS/IN, scalar literals, aliases, CAST/EXTRACT, explicit aggregates,
COUNT DISTINCT, FILTER, OVER, WITHIN GROUP, and UNION/INTERSECT/EXCEPT. Every
node, nonempty argument, real table and nested call receives the same review
before and after PostgreSQL regeneration. Unknown parser shapes fail closed.
Writes, commands, SET/role changes, catalog/temp schemas, table functions,
locks, SELECT INTO, CTE shadowing, and unreviewed calls remain unexecuted.

Columns are deliberately left to PostgreSQL grants (FR-5.8). Evaluation owns
wall-clock lint (FR-5.9), and the existing executor owns timeout/resource
controls (FR-5.10/FR-6.11). Parsing or a row cap is no query-cost guarantee.
The profile is trusted source configuration, never persona/model input.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Mapping

from ..contracts import ExecutionMode, Persona, ReasonCode
from ..db.executor import HarnessSelectReview, SelectReview
from ..errors import ConfigurationError, HarnessSafetyStopError, SQLValidationError
from ..policy.loader import PolicyMatrix
from .function_policy import (
    FUNCTION_POLICY_REVISION,
    RULES_BY_ID,
    FunctionPolicyViolation,
    ReviewedFunctionPolicy,
)


VALIDATOR_REVISION = "fr5-validator-draft-2"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")


class ValidationRuleCode(str, Enum):
    """Internal diagnostic rules, separate from the shared public ReasonCode."""

    ACCEPTED = "V-ACCEPTED"
    INPUT = "V-INPUT"
    REVIEW_REQUIRED = "V-REVIEW-REQUIRED"
    PARSER_UNAVAILABLE = "V-PARSER-UNAVAILABLE"
    PARSER_PROFILE = "V-PARSER-PROFILE"
    POLICY_BINDING = "V-POLICY-BINDING"
    PARSE = "V-PARSE"
    STATEMENT_COUNT = "V-STATEMENT-COUNT"
    TOP_LEVEL = "V-TOP-LEVEL"
    UNSUPPORTED_NODE = "V-UNSUPPORTED-NODE"
    UNSUPPORTED_ARGUMENT = "V-UNSUPPORTED-ARGUMENT"
    EXECUTABLE_STATEMENT = "V-EXECUTABLE-STATEMENT"
    STRUCTURE = "V-STRUCTURE"
    SCHEMA = "V-SCHEMA"
    TABLE = "V-TABLE"
    TABLE_FUNCTION = "V-TABLE-FUNCTION"
    CTE_SHADOW = "V-CTE-SHADOW"
    FUNCTION = "V-FUNCTION"
    REGENERATION = "V-REGENERATION"
    IDEMPOTENCE = "V-IDEMPOTENCE"


@dataclass(frozen=True, slots=True)
class ValidationDecision:
    """Private review output; rejected candidates never carry executable SQL."""

    accepted: bool
    reason_code: ReasonCode
    rule_code: ValidationRuleCode
    internal_detail: str
    regenerated_sql: str | None
    validator_revision: str


@dataclass(frozen=True, slots=True)
class NodeShape:
    """A proposed exact class/argument layout requiring installed-parser review."""

    parser_class: str
    argument_keys: frozenset[str]
    scalar_keys: frozenset[str] = frozenset()


# Explicit exact classes, never blanket Expression/Func/Query acceptance.
# An absent optional class is unavailable; it never broadens to a base class.
_SHAPES: tuple[NodeShape, ...] = (
    NodeShape("Select", frozenset({"expressions", "from", "from_", "joins", "where", "group", "having", "order", "limit", "offset", "distinct", "with", "with_"})),
    NodeShape("Union", frozenset({"this", "expression", "distinct", "with", "with_", "order", "limit", "offset"}), frozenset({"distinct"})),
    NodeShape("Intersect", frozenset({"this", "expression", "distinct", "with", "with_", "order", "limit", "offset"}), frozenset({"distinct"})),
    NodeShape("Except", frozenset({"this", "expression", "distinct", "with", "with_", "order", "limit", "offset"}), frozenset({"distinct"})),
    NodeShape("With", frozenset({"expressions", "recursive"}), frozenset({"recursive"})),
    NodeShape("CTE", frozenset({"this", "alias", "materialized"}), frozenset({"materialized"})),
    NodeShape("Table", frozenset({"this", "db", "catalog", "alias"})),
    NodeShape("TableAlias", frozenset({"this", "columns"})),
    NodeShape("From", frozenset({"this", "expressions"})),
    NodeShape("Join", frozenset({"this", "on", "using", "kind", "side"}), frozenset({"kind", "side"})),
    NodeShape("Subquery", frozenset({"this", "alias"})),
    NodeShape("Alias", frozenset({"this", "alias"})),
    NodeShape("Column", frozenset({"this", "table", "db", "catalog"})),
    NodeShape("Identifier", frozenset({"this", "quoted"}), frozenset({"this", "quoted"})),
    NodeShape("Var", frozenset({"this"}), frozenset({"this"})),
    NodeShape("Literal", frozenset({"this", "is_string"}), frozenset({"this", "is_string"})),
    NodeShape("Boolean", frozenset({"this"}), frozenset({"this"})),
    NodeShape("Null", frozenset()),
    NodeShape("Star", frozenset()),
    NodeShape("Where", frozenset({"this"})),
    NodeShape("Having", frozenset({"this"})),
    NodeShape("Group", frozenset({"expressions"})),
    NodeShape("Order", frozenset({"expressions"})),
    NodeShape("Ordered", frozenset({"this", "desc", "nulls_first"}), frozenset({"desc", "nulls_first"})),
    NodeShape("Limit", frozenset({"expression"})),
    NodeShape("Offset", frozenset({"expression"})),
    NodeShape("Distinct", frozenset({"expressions", "on"})),
    NodeShape("Paren", frozenset({"this"})),
    NodeShape("Tuple", frozenset({"expressions"})),
    NodeShape("And", frozenset({"this", "expression"})),
    NodeShape("Or", frozenset({"this", "expression"})),
    NodeShape("Not", frozenset({"this"})),
    NodeShape("EQ", frozenset({"this", "expression"})),
    NodeShape("NEQ", frozenset({"this", "expression"})),
    NodeShape("GT", frozenset({"this", "expression"})),
    NodeShape("GTE", frozenset({"this", "expression"})),
    NodeShape("LT", frozenset({"this", "expression"})),
    NodeShape("LTE", frozenset({"this", "expression"})),
    NodeShape("Is", frozenset({"this", "expression"})),
    NodeShape("Between", frozenset({"this", "low", "high"})),
    NodeShape("In", frozenset({"this", "expressions", "query"})),
    NodeShape("Like", frozenset({"this", "expression"})),
    NodeShape("ILike", frozenset({"this", "expression"})),
    NodeShape("Escape", frozenset({"this", "expression"})),
    NodeShape("Add", frozenset({"this", "expression"})),
    NodeShape("Sub", frozenset({"this", "expression"})),
    NodeShape("Mul", frozenset({"this", "expression"})),
    NodeShape("Div", frozenset({"this", "expression", "typed", "safe"}), frozenset({"typed", "safe"})),
    NodeShape("Mod", frozenset({"this", "expression"})),
    NodeShape("Neg", frozenset({"this"})),
    # These are grammar/control expressions even if a parser Func is a base.
    NodeShape("Case", frozenset({"this", "ifs", "default"})),
    NodeShape("If", frozenset({"this", "true", "false"})),
    NodeShape("Exists", frozenset({"this"})),
    NodeShape("Filter", frozenset({"this", "expression"})),
    NodeShape("WithinGroup", frozenset({"this", "expression"})),
    NodeShape("Window", frozenset({"this", "partition_by", "order", "spec", "over"}), frozenset({"over"})),
    NodeShape("WindowSpec", frozenset({"kind", "start", "start_side", "end", "end_side"}), frozenset({"kind", "start", "start_side", "end", "end_side"})),
    NodeShape("DataType", frozenset({"this", "expressions", "nested"}), frozenset({"this", "nested"})),
    NodeShape("DataTypeParam", frozenset({"this"})),
    NodeShape("Interval", frozenset({"this", "unit"})),
)
PROPOSED_NODE_SHAPES: Mapping[str, NodeShape] = MappingProxyType({shape.parser_class: shape for shape in _SHAPES})
_QUERY_NAMES = frozenset({"Select", "Union", "Intersect", "Except"})
_DENY_NAMES = frozenset({
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "TruncateTable",
    "Set", "Command", "Copy", "Values", "Into", "Lock", "Transaction", "Commit", "Rollback",
    "Grant", "Revoke", "Use", "Execute", "Prepare", "Analyze", "Explain", "Pragma", "Attach",
    "Detach", "LoadData", "Cache", "Uncache", "Kill", "Show", "Describe", "Export", "Import",
})


@dataclass(frozen=True, slots=True)
class ParserReviewApproval:
    """External review metadata, supplied only by trusted future composition.

    Construction records evidence supplied by the caller, never produces it.
    review_reference identifies actual human review and per-signature positive
    and negative contracts. Pinning/version drift causes fail-closed rejection.
    No default approval object or fabricated reference is present in source.
    """

    sqlglot_version: str
    validator_revision: str
    function_policy_revision: str
    approved_node_shapes: frozenset[str]
    approved_function_rule_ids: frozenset[str]
    review_reference: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.sqlglot_version, self.validator_revision, self.function_policy_revision, self.review_reference
        )):
            raise ConfigurationError("Parser review metadata requires actual nonempty version/review references.")
        if self.validator_revision != VALIDATOR_REVISION or self.function_policy_revision != FUNCTION_POLICY_REVISION:
            raise ConfigurationError("Parser review metadata belongs to different draft source revisions.")
        if type(self.approved_node_shapes) is not frozenset or type(self.approved_function_rule_ids) is not frozenset:
            raise ConfigurationError("Reviewed shape and function selections must be immutable sets.")
        if not self.approved_node_shapes or not self.approved_node_shapes <= PROPOSED_NODE_SHAPES.keys():
            raise ConfigurationError("Reviewed AST shapes must be explicit authored representations.")
        if not self.approved_function_rule_ids <= RULES_BY_ID.keys():
            raise ConfigurationError("Unknown function review rule IDs cannot expand the policy.")
        if "Select" not in self.approved_node_shapes:
            raise ConfigurationError("A reviewed SELECT representation is required.")

    @property
    def fingerprint(self) -> str:
        payload = {
            "sqlglot_version": self.sqlglot_version,
            "validator_revision": self.validator_revision,
            "function_policy_revision": self.function_policy_revision,
            "approved_node_shapes": sorted(self.approved_node_shapes),
            "approved_function_rule_ids": sorted(self.approved_function_rule_ids),
            "review_reference": self.review_reference,
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class _Rejected(Exception):
    def __init__(self, code: ValidationRuleCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _present(value: object) -> bool:
    return value is not None and value is not False and value != [] and value != ()


def _require_hash(value: object, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise _Rejected(ValidationRuleCode.POLICY_BINDING, f"{label} is not an actual lowercase SHA-256 fingerprint.")


def _leading_keyword(text: str) -> str:
    """Supplement AST rules by excluding TABLE/VALUES parser sugar at entry.

    Only whitespace and SQL comments are skipped. This is not statement
    splitting; sqlglot.parse remains authoritative for the statement count.
    Parenthesized top-level query entry is deliberately outside this profile.
    """
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text.startswith("--", index):
            end = text.find("\n", index + 2)
            index = len(text) if end < 0 else end + 1
        elif text.startswith("/*", index):
            index += 2
            depth = 1
            while index < len(text) and depth:
                if text.startswith("/*", index):
                    depth += 1
                    index += 2
                elif text.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            if depth:
                return ""
        else:
            end = index
            while end < len(text) and (text[end].isalpha() or text[end] == "_"):
                end += 1
            return text[index:end].upper()
    return ""


class _ASTReview:
    def __init__(self, parser: object, approval: ParserReviewApproval, *, permitted_tables: frozenset[str], real_tables: frozenset[str], max_nodes: int) -> None:
        self.parser = parser
        self.exp = getattr(parser, "exp", None)
        expression_class = getattr(self.exp, "Expression", None)
        func_class = getattr(self.exp, "Func", None)
        if not isinstance(expression_class, type) or not isinstance(func_class, type):
            raise _Rejected(ValidationRuleCode.PARSER_PROFILE, "Parser Expression/Func capabilities are unavailable.")
        self.expression_class = expression_class
        self.func_class = func_class
        self.classes: dict[str, type] = {}
        self.shapes: dict[type, NodeShape] = {}
        for name in sorted(approval.approved_node_shapes):
            cls = getattr(self.exp, name, None)
            if not isinstance(cls, type) or not issubclass(cls, expression_class):
                raise _Rejected(ValidationRuleCode.PARSER_PROFILE, f"Reviewed AST capability is unavailable: {name}.")
            if cls in self.shapes:
                raise _Rejected(ValidationRuleCode.PARSER_PROFILE, "Parser aliases merge independently reviewed node layouts.")
            self.classes[name] = cls
            self.shapes[cls] = PROPOSED_NODE_SHAPES[name]
        self.denied_classes = tuple(cls for name in sorted(_DENY_NAMES) if isinstance(cls := getattr(self.exp, name, None), type))
        try:
            self.functions = ReviewedFunctionPolicy(self.exp, approval.approved_function_rule_ids)
        except (FunctionPolicyViolation, KeyError) as exc:
            raise _Rejected(ValidationRuleCode.PARSER_PROFILE, str(exc)) from exc
        self.permitted_tables = permitted_tables
        self.real_tables = real_tables
        self.max_nodes = max_nodes

    def _is(self, node: object, name: str) -> bool:
        cls = self.classes.get(name)
        return cls is not None and type(node) is cls

    def _query(self, node: object) -> bool:
        return any(self._is(node, name) for name in _QUERY_NAMES)

    def _identifier(self, node: object) -> str:
        if not self._is(node, "Identifier"):
            raise _Rejected(ValidationRuleCode.STRUCTURE, "An object name is not a reviewed Identifier node.")
        text = node.args.get("this")
        quoted = node.args.get("quoted", False)
        if not isinstance(text, str) or _IDENTIFIER.fullmatch(text) is None or type(quoted) is not bool:
            raise _Rejected(ValidationRuleCode.STRUCTURE, "Unsupported identifier representation.")
        return text if quoted else text.lower()

    def _children(self, node: object):
        if not isinstance(node.args, dict):
            raise _Rejected(ValidationRuleCode.PARSER_PROFILE, "AST args are not the reviewed mapping representation.")
        for value in node.args.values():
            if isinstance(value, self.expression_class):
                yield value
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if not isinstance(item, self.expression_class):
                        raise _Rejected(ValidationRuleCode.UNSUPPORTED_ARGUMENT, "An AST collection contains non-expression values.")
                    yield item

    def _guard_structure(self, node: object, name: str) -> None:
        args = node.args
        if name in _QUERY_NAMES:
            if name == "Select":
                if not isinstance(args.get("expressions"), list) or not args["expressions"]:
                    raise _Rejected(ValidationRuleCode.STRUCTURE, "SELECT requires an explicit projection list.")
            elif not self._query(args.get("this")) and not self._is(args.get("this"), "Subquery"):
                raise _Rejected(ValidationRuleCode.STRUCTURE, "Set operation has no SELECT-family left operand.")
            elif not self._query(args.get("expression")) and not self._is(args.get("expression"), "Subquery"):
                raise _Rejected(ValidationRuleCode.STRUCTURE, "Set operation has no SELECT-family right operand.")
            if _present(args.get("with")) and _present(args.get("with_")):
                raise _Rejected(ValidationRuleCode.PARSER_PROFILE, "Multiple parser WITH representations are present.")
            if _present(args.get("from")) and _present(args.get("from_")):
                raise _Rejected(ValidationRuleCode.PARSER_PROFILE, "Multiple parser FROM representations are present.")
        if name == "With":
            if _present(args.get("recursive")):
                raise _Rejected(ValidationRuleCode.STRUCTURE, "Recursive CTEs are outside the reviewed grammar.")
            if not args.get("expressions") or any(not self._is(item, "CTE") for item in args["expressions"]):
                raise _Rejected(ValidationRuleCode.STRUCTURE, "WITH requires ordinary CTE definitions.")
        if name in {"Subquery", "CTE", "Exists"} and not self._query(args.get("this")):
            raise _Rejected(ValidationRuleCode.EXECUTABLE_STATEMENT, "A nested executable body is not SELECT-family.")
        if name == "CTE" and not self._is(args.get("alias"), "TableAlias"):
            raise _Rejected(ValidationRuleCode.STRUCTURE, "A CTE requires an ordinary alias.")
        if name in {"From", "Join"}:
            relations = [args["this"]] if args.get("this") is not None else []
            relations.extend(args.get("expressions") or [])
            if not relations or any(not self._is(item, "Table") and not self._is(item, "Subquery") for item in relations):
                raise _Rejected(ValidationRuleCode.TABLE_FUNCTION, "FROM/JOIN admits only physical/CTE tables and SELECT subqueries.")
        if name == "Join":
            if args.get("kind") not in {None, "", "INNER", "CROSS"} or args.get("side") not in {None, "", "LEFT", "RIGHT", "FULL"}:
                raise _Rejected(ValidationRuleCode.STRUCTURE, "Unreviewed JOIN kind or side.")
        if name == "Identifier":
            self._identifier(node)
        if name == "Var":
            parent = getattr(node, "parent", None)
            if not isinstance(args.get("this"), str) or type(parent).__name__ not in {"Extract", "TimestampTrunc", "Interval"}:
                raise _Rejected(ValidationRuleCode.STRUCTURE, "Bare executable/variable syntax is not admitted.")
        if name == "Literal":
            if not isinstance(args.get("this"), str) or type(args.get("is_string")) is not bool:
                raise _Rejected(ValidationRuleCode.STRUCTURE, "Unreviewed literal representation.")
        if name == "Boolean" and type(args.get("this")) is not bool:
            raise _Rejected(ValidationRuleCode.STRUCTURE, "Unreviewed boolean representation.")
        if name in {"Union", "Intersect", "Except", "CTE", "Ordered", "DataType"}:
            for key in {"distinct", "materialized", "desc", "nulls_first", "nested"} & args.keys():
                if args[key] is not None and type(args[key]) is not bool:
                    raise _Rejected(ValidationRuleCode.STRUCTURE, "A reviewed boolean argument has an unknown representation.")
        if name == "Div" and any(_present(args.get(key)) for key in ("typed", "safe")):
            raise _Rejected(ValidationRuleCode.STRUCTURE, "Dialect-specific division flags are outside this profile.")
        if name == "Column":
            if not self._is(args.get("this"), "Identifier") and not self._is(args.get("this"), "Star"):
                raise _Rejected(ValidationRuleCode.STRUCTURE, "Unreviewed column expression.")
            self._qualifiers(args)
        if name == "Table":
            if not self._is(args.get("this"), "Identifier"):
                raise _Rejected(ValidationRuleCode.TABLE_FUNCTION, "A physical table name cannot be a callable expression.")
            self._qualifiers(args)
        if name in {"TableAlias", "Alias"}:
            self._identifier(args.get("this") if name == "TableAlias" else args.get("alias"))
            for column in args.get("columns") or []:
                self._identifier(column)
        if name == "DataType":
            try:
                self.functions.require_scalar_type(node)
            except FunctionPolicyViolation as exc:
                raise _Rejected(ValidationRuleCode.FUNCTION, str(exc)) from exc
        if name == "Interval":
            value = args.get("this")
            unit = args.get("unit")
            if not self._is(value, "Literal") or (unit is not None and not self._is(unit, "Var") and not self._is(unit, "Identifier")):
                raise _Rejected(ValidationRuleCode.STRUCTURE, "INTERVAL requires a literal with a scalar unit.")
        if name == "Filter":
            if not self._is(args.get("expression"), "Where"):
                raise _Rejected(ValidationRuleCode.STRUCTURE, "FILTER requires the reviewed WHERE predicate representation.")
            call = args.get("this")
            if self._is(call, "WithinGroup"):
                call = call.args.get("this")
            try:
                rule = self.functions.require(call)
            except (FunctionPolicyViolation, AttributeError) as exc:
                raise _Rejected(ValidationRuleCode.FUNCTION, "FILTER target has no reviewed aggregate signature.") from exc
            if rule.sql_name not in {"count", "sum", "avg", "min", "max", "percentile_cont"}:
                raise _Rejected(ValidationRuleCode.FUNCTION, "FILTER target is not a reviewed aggregate.")
        if name == "WithinGroup":
            call = args.get("this")
            try:
                rule = self.functions.require(call)
            except (FunctionPolicyViolation, AttributeError) as exc:
                raise _Rejected(ValidationRuleCode.FUNCTION, "WITHIN GROUP has no reviewed ordered-set aggregate.") from exc
            if rule.sql_name != "percentile_cont":
                raise _Rejected(ValidationRuleCode.FUNCTION, "This WITHIN GROUP overload is unreviewed.")
        if name == "Window":
            if args.get("over") not in {None, "OVER"} or args.get("this") is None:
                raise _Rejected(ValidationRuleCode.STRUCTURE, "Only an explicit function OVER window is admitted.")
            call = args["this"]
            if self._is(call, "Filter"):
                call = call.args.get("this")
            try:
                rule = self.functions.require(call)
            except (FunctionPolicyViolation, AttributeError) as exc:
                raise _Rejected(ValidationRuleCode.FUNCTION, "OVER target has no reviewed function signature.") from exc
            if rule.sql_name not in {"count", "sum", "avg", "min", "max", "row_number", "rank", "dense_rank"}:
                raise _Rejected(ValidationRuleCode.FUNCTION, "This OVER overload is unreviewed.")
        if name == "WindowSpec":
            if args.get("kind") not in {"ROWS", "RANGE", "GROUPS"}:
                raise _Rejected(ValidationRuleCode.STRUCTURE, "Unknown window frame kind.")
            for key in ("start_side", "end_side"):
                if args.get(key) not in {None, "", "PRECEDING", "FOLLOWING"}:
                    raise _Rejected(ValidationRuleCode.STRUCTURE, "Unknown window frame direction.")
            for key in ("start", "end"):
                value = args.get(key)
                if value is not None and not isinstance(value, self.expression_class) and value not in {"UNBOUNDED", "CURRENT ROW"}:
                    raise _Rejected(ValidationRuleCode.STRUCTURE, "Unknown window frame boundary.")

    def _qualifiers(self, args: dict) -> None:
        if _present(args.get("catalog")):
            raise _Rejected(ValidationRuleCode.SCHEMA, "Catalog-qualified objects are excluded.")
        if _present(args.get("db")) and self._identifier(args["db"]) != "public":
            raise _Rejected(ValidationRuleCode.SCHEMA, "Only unqualified/public application objects are admitted.")

    def _walk_all(self, root: object) -> None:
        pending = [root]
        observed: set[int] = set()
        while pending:
            node = pending.pop()
            if not isinstance(node, self.expression_class) or id(node) in observed:
                raise _Rejected(ValidationRuleCode.STRUCTURE, "AST is not a finite, singly owned expression tree.")
            observed.add(id(node))
            if len(observed) > self.max_nodes:
                raise _Rejected(ValidationRuleCode.INPUT, "Candidate exceeds the configured parser-node input limit.")
            if isinstance(node, self.denied_classes):
                raise _Rejected(ValidationRuleCode.EXECUTABLE_STATEMENT, f"Executable statement/locking node is forbidden: {type(node).__name__}.")
            shape = self.shapes.get(type(node))
            if shape is not None:
                args = node.args
                unknown = {key for key, value in args.items() if _present(value)} - shape.argument_keys
                if unknown:
                    raise _Rejected(ValidationRuleCode.UNSUPPORTED_ARGUMENT, f"Unreviewed arguments on {shape.parser_class}: {sorted(unknown)}.")
                for key, value in args.items():
                    if _present(value) and key in shape.argument_keys and not isinstance(value, (self.expression_class, list, tuple)) and key not in shape.scalar_keys:
                        raise _Rejected(ValidationRuleCode.UNSUPPORTED_ARGUMENT, "An expression argument has unreviewed scalar content.")
                self._guard_structure(node, shape.parser_class)
            elif isinstance(node, self.func_class) or self.functions.is_special(node) or self.functions.has_reviewed_representation(node):
                try:
                    rule = self.functions.require(node)
                except FunctionPolicyViolation as exc:
                    raise _Rejected(ValidationRuleCode.FUNCTION, str(exc)) from exc
                for key, value in node.args.items():
                    if _present(value) and not isinstance(value, (self.expression_class, list, tuple)):
                        if not (rule.parser_class == "Anonymous" and key == "this" and isinstance(value, str)):
                            raise _Rejected(ValidationRuleCode.FUNCTION, "A callable argument has unreviewed scalar content.")
            else:
                raise _Rejected(ValidationRuleCode.UNSUPPORTED_NODE, f"Unreviewed AST class: {type(node).__name__}.")
            pending.extend(self._children(node))

    def _walk_tables(self, node: object, visible_ctes: frozenset[str]) -> None:
        if self._query(node):
            local = set(visible_ctes)
            with_node = node.args.get("with_") or node.args.get("with")
            if with_node is not None:
                if not self._is(with_node, "With"):
                    raise _Rejected(ValidationRuleCode.STRUCTURE, "WITH node is not its reviewed class.")
                defined_here = set()
                for cte in with_node.args.get("expressions") or []:
                    alias = cte.args.get("alias")
                    if not self._is(alias, "TableAlias"):
                        raise _Rejected(ValidationRuleCode.STRUCTURE, "CTE alias has an unknown shape.")
                    name = self._identifier(alias.args.get("this"))
                    if name.lower() in self.real_tables:
                        raise _Rejected(ValidationRuleCode.CTE_SHADOW, "CTE alias shadows a real fixture table, including restricted tables.")
                    if name in defined_here:
                        raise _Rejected(ValidationRuleCode.CTE_SHADOW, "Duplicate CTE names in one scope are excluded.")
                    # Nonrecursive CTEs see their parents and earlier siblings,
                    # never their own name or a later sibling. Nested WITH
                    # scopes are independent, preserving SQL lexical binding.
                    self._walk_tables(cte.args["this"], frozenset(local))
                    local.add(name)
                    defined_here.add(name)
            for key, value in node.args.items():
                if key in {"with", "with_"}:
                    continue
                if isinstance(value, self.expression_class):
                    self._walk_tables(value, frozenset(local))
                elif isinstance(value, (list, tuple)):
                    for child in value:
                        self._walk_tables(child, frozenset(local))
            return
        if self._is(node, "Table"):
            name = self._identifier(node.args.get("this"))
            qualified = _present(node.args.get("db"))
            if not qualified and name in visible_ctes:
                return
            if name not in self.real_tables or name not in self.permitted_tables:
                raise _Rejected(ValidationRuleCode.TABLE, "A real table is absent from the permitted policy set.")
            return
        for child in self._children(node):
            self._walk_tables(child, visible_ctes)

    def review(self, root: object) -> None:
        if not self._query(root):
            raise _Rejected(ValidationRuleCode.TOP_LEVEL, "Top level is not an explicitly reviewed SELECT/UNION/INTERSECT/EXCEPT.")
        self._walk_all(root)
        self._walk_tables(root, frozenset())


class ReviewedSQLValidator:
    """Source-controlled implementation of the existing executor's protocol."""

    def __init__(self, policy: PolicyMatrix, *, approval: ParserReviewApproval | None = None, max_sql_bytes: int = 131_072, max_ast_nodes: int = 10_000) -> None:
        if type(policy) is not PolicyMatrix or policy.schema != "public":
            raise ConfigurationError("The loaded public-schema access matrix is required.")
        if approval is not None and type(approval) is not ParserReviewApproval:
            raise ConfigurationError("Parser approval must be trusted typed review metadata.")
        if type(max_sql_bytes) is not int or max_sql_bytes < 1 or type(max_ast_nodes) is not int or max_ast_nodes < 1:
            raise ConfigurationError("Positive parser input-size bounds are required.")
        self.policy = policy
        self.approval = approval
        self.max_sql_bytes = max_sql_bytes
        self.max_ast_nodes = max_ast_nodes

    @property
    def revision(self) -> str:
        return VALIDATOR_REVISION if self.approval is None else f"{VALIDATOR_REVISION}:{self.approval.sqlglot_version}:{self.approval.fingerprint}"

    def _parser(self) -> object:
        if self.approval is None:
            raise _Rejected(ValidationRuleCode.REVIEW_REQUIRED, "Actual human parser-layout/function-signature review evidence is unavailable.")
        try:
            import sqlglot
        except ImportError as exc:
            raise _Rejected(ValidationRuleCode.PARSER_UNAVAILABLE, "sqlglot is unavailable in the future runtime environment.") from exc
        if getattr(sqlglot, "__version__", None) != self.approval.sqlglot_version:
            raise _Rejected(ValidationRuleCode.PARSER_PROFILE, "Installed sqlglot release differs from the actual reviewed release.")
        if not callable(getattr(sqlglot, "parse", None)):
            raise _Rejected(ValidationRuleCode.PARSER_PROFILE, "The reviewed plural-statement parse capability is unavailable.")
        return sqlglot

    def _parse_one(self, parser: object, text: str) -> object:
        if _leading_keyword(text) not in {"SELECT", "WITH"}:
            raise _Rejected(ValidationRuleCode.TOP_LEVEL, "Only SELECT/WITH query entry is admitted; TABLE/VALUES/commands are excluded.")
        errors = getattr(parser, "errors", None)
        error_level = getattr(getattr(errors, "ErrorLevel", None), "RAISE", None)
        if error_level is None:
            raise _Rejected(ValidationRuleCode.PARSER_PROFILE, "Strict parser-error capability is unavailable.")
        try:
            statements = parser.parse(text, read="postgres", error_level=error_level)
        except Exception as exc:
            raise _Rejected(ValidationRuleCode.PARSE, f"PostgreSQL parsing rejected candidate: {type(exc).__name__}.") from exc
        if not isinstance(statements, list) or len(statements) != 1 or statements[0] is None:
            raise _Rejected(ValidationRuleCode.STATEMENT_COUNT, "Plural parsing must return exactly one nonempty statement.")
        return statements[0]

    def _decision(self, candidate_sql: str, *, persona: Persona, policy_fingerprint: str, allow_all_fixture_tables: bool = False) -> ValidationDecision:
        try:
            if type(persona) is not Persona:
                raise _Rejected(ValidationRuleCode.POLICY_BINDING, "A typed persona is required.")
            _require_hash(policy_fingerprint, "Access matrix fingerprint")
            if policy_fingerprint != self.policy.sha256:
                raise _Rejected(ValidationRuleCode.POLICY_BINDING, "Requested policy fingerprint differs from the loaded matrix.")
            try:
                role = self.policy.role(persona.business_role)
            except ConfigurationError as exc:
                raise _Rejected(ValidationRuleCode.POLICY_BINDING, "Persona business role is absent from the matrix.") from exc
            if persona.login_role != role.login_role:
                raise _Rejected(ValidationRuleCode.POLICY_BINDING, "Persona login role does not match the business role.")
            if not isinstance(candidate_sql, str) or not candidate_sql.strip():
                raise _Rejected(ValidationRuleCode.INPUT, "A nonempty SQL candidate is required.")
            if len(candidate_sql.encode("utf-8", errors="strict")) > self.max_sql_bytes:
                raise _Rejected(ValidationRuleCode.INPUT, "Candidate exceeds the configured parser-byte input limit.")
            parser = self._parser()
            assert self.approval is not None  # guarded trusted configuration, never a SQL safety assertion
            permitted = frozenset(self.policy.tables if allow_all_fixture_tables else role.tables)
            ast_review = _ASTReview(parser, self.approval, permitted_tables=permitted, real_tables=frozenset(self.policy.tables), max_nodes=self.max_ast_nodes)
            first = self._parse_one(parser, candidate_sql)
            ast_review.review(first)
            try:
                regenerated = first.sql(dialect="postgres")
            except Exception as exc:
                raise _Rejected(ValidationRuleCode.REGENERATION, "PostgreSQL AST regeneration failed.") from exc
            if not isinstance(regenerated, str) or not regenerated.strip():
                raise _Rejected(ValidationRuleCode.REGENERATION, "AST regeneration yielded no SQL.")
            second = self._parse_one(parser, regenerated)
            # Same exhaustive scope/structure/function policy on output: a
            # renderer normalization may not smuggle in a newly shaped call.
            ast_review.review(second)
            try:
                regenerated_again = second.sql(dialect="postgres")
            except Exception as exc:
                raise _Rejected(ValidationRuleCode.REGENERATION, "Second PostgreSQL regeneration failed.") from exc
            if regenerated_again != regenerated:
                raise _Rejected(ValidationRuleCode.IDEMPOTENCE, "Parse/regenerate PostgreSQL text is not idempotent.")
            return ValidationDecision(True, ReasonCode.ANSWERED, ValidationRuleCode.ACCEPTED, "SELECT-family AST and regenerated text meet the injected reviewed profile.", regenerated, self.revision)
        except _Rejected as exc:
            dependency = exc.code in {ValidationRuleCode.REVIEW_REQUIRED, ValidationRuleCode.PARSER_UNAVAILABLE, ValidationRuleCode.PARSER_PROFILE}
            reason = ReasonCode.MISSING_DEPENDENCY if dependency else ReasonCode.VALIDATOR_REJECTED
            return ValidationDecision(False, reason, exc.code, exc.detail, None, self.revision)
        except Exception as exc:
            # No parser/profile/internal exception can result in raw execution.
            return ValidationDecision(False, ReasonCode.VALIDATOR_REJECTED, ValidationRuleCode.UNSUPPORTED_NODE, f"Unsupported review capability/shape: {type(exc).__name__}.", None, self.revision)

    def validate(self, candidate_sql: str, *, persona: Persona, policy_fingerprint: str) -> ValidationDecision:
        """Return private accepted/rejected metadata; this method never executes."""
        return self._decision(candidate_sql, persona=persona, policy_fingerprint=policy_fingerprint)

    def review_select(self, candidate_sql: str, *, persona: Persona, policy_fingerprint: str) -> SelectReview:
        decision = self.validate(candidate_sql, persona=persona, policy_fingerprint=policy_fingerprint)
        if not decision.accepted or decision.regenerated_sql is None:
            error = SQLValidationError(f"{decision.rule_code.value}: {decision.internal_detail}", reason_code=decision.reason_code)
            error.validation_rule_code = decision.rule_code
            raise error
        return SelectReview(decision.regenerated_sql, persona.principal_id, persona.login_role, persona.business_role, policy_fingerprint, decision.validator_revision)


class HarnessSafetyReviewer:
    """Mandatory independent safety gate; it grants no connection capability.

    UNCONTROLLED relaxes only role table visibility to the known fixture table
    set. The same parser/AST/function/schema review still applies, with no
    privileged/catalog/UDF/unsafe-statement fallback. Other harness modes keep
    persona table rules, including FULL clone evaluations that also require the
    executor's separate authorization receipt. This interface admits a defined
    mode but supplies no EvaluationConnectionSource or clone capability. Exact
    clone provenance and least-privilege credential audits remain owned by
    db.connections and the existing evaluation executor.
    """

    def __init__(self, policy: PolicyMatrix, *, approval: ParserReviewApproval | None = None, max_sql_bytes: int = 131_072, max_ast_nodes: int = 10_000) -> None:
        self._validator = ReviewedSQLValidator(policy, approval=approval, max_sql_bytes=max_sql_bytes, max_ast_nodes=max_ast_nodes)

    def review_candidate(self, candidate_sql: str, *, persona: Persona, mode: ExecutionMode, policy_fingerprint: str, clone_token: str, fixture_dump_fingerprint: str) -> HarnessSelectReview:
        try:
            if type(mode) is not ExecutionMode:
                raise _Rejected(ValidationRuleCode.POLICY_BINDING, "An explicit defined evaluation mode is required.")
            _require_hash(fixture_dump_fingerprint, "Actual fixture dump fingerprint")
            if not isinstance(clone_token, str) or not clone_token.strip():
                raise _Rejected(ValidationRuleCode.POLICY_BINDING, "An audited disposable clone token is required.")
            decision = self._validator._decision(candidate_sql, persona=persona, policy_fingerprint=policy_fingerprint, allow_all_fixture_tables=mode is ExecutionMode.UNCONTROLLED)
            if not decision.accepted or decision.regenerated_sql is None:
                raise _Rejected(decision.rule_code, decision.internal_detail)
            return HarnessSelectReview(
                regenerated_sql=decision.regenerated_sql,
                candidate_fingerprint=sha256(candidate_sql.encode("utf-8")).hexdigest(),
                mode=mode,
                principal_id=persona.principal_id,
                policy_fingerprint=policy_fingerprint,
                clone_token=clone_token,
                fixture_dump_fingerprint=fixture_dump_fingerprint,
                safety_reviewer_revision=decision.validator_revision,
            )
        except _Rejected as exc:
            error = HarnessSafetyStopError(f"{exc.code.value}: {exc.detail}")
            error.validation_rule_code = exc.code
            raise error from exc
        except Exception as exc:
            raise HarnessSafetyStopError(f"Harness AST safety review unavailable: {type(exc).__name__}.") from exc
