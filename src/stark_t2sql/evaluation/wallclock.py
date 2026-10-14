"""Independent FR-9.6 AST lint; the production validator is not changed.

Parser imports and inspection happen only when a future caller explicitly
invokes lint_wallclock. Unavailable parser/profile capabilities are reported as
unavailable, never treated as an empty, successfully inspected syntax tree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WallClockReview:
    sqlglot_version: str
    review_reference: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.sqlglot_version, self.review_reference)):
            raise ValueError("Actual pinned parser version and wall-clock layout review are required")


@dataclass(frozen=True, slots=True)
class WallClockViolation:
    node_kind: str
    rule: str


@dataclass(frozen=True, slots=True)
class WallClockLintResult:
    available: bool
    violations: tuple[WallClockViolation, ...] = ()
    unavailable_reason: str | None = None

    @property
    def uses_wallclock(self) -> bool:
        return bool(self.violations)


class _Unavailable(Exception):
    pass


def _class(namespace: object, name: str, base: type | None = None) -> type:
    candidate = getattr(namespace, name, None)
    if not isinstance(candidate, type) or (base is not None and not issubclass(candidate, base)):
        raise _Unavailable(f"Reviewed AST capability is unavailable: {name}")
    return candidate


def _args(node: object) -> Mapping:
    args = getattr(node, "args", None)
    if not isinstance(args, Mapping):
        raise _Unavailable("AST argument representation differs from the reviewed mapping layout")
    return args


def _type_name(node: object) -> str:
    scalar = _args(node).get("this")
    if isinstance(scalar, str):
        return scalar.upper()
    value = getattr(scalar, "value", None)
    name = getattr(scalar, "name", None)
    if isinstance(value, str):
        return value.upper()
    if isinstance(name, str):
        return name.upper()
    raise _Unavailable("Cast target has an unreviewed scalar type representation")


def lint_wallclock(sql: str, *, review: WallClockReview | None = None, max_ast_nodes: int = 10_000) -> WallClockLintResult:
    """Parse, never execute, one PostgreSQL candidate and inspect every node.

The evaluator may call this even when the validator rejected a candidate. A
parser failure is not reclassified as FC-SYNTAX without database SQLSTATE
42601; that failure remains a separate unavailable lint dependency.
"""
    if review is None:
        return WallClockLintResult(False, unavailable_reason="Actual pinned wall-clock parser review is unavailable")
    if type(review) is not WallClockReview or type(max_ast_nodes) is not int or max_ast_nodes < 1:
        return WallClockLintResult(False, unavailable_reason="Invalid wall-clock parser review or AST bound")
    if not isinstance(sql, str) or not sql.strip():
        return WallClockLintResult(False, unavailable_reason="There is no candidate SQL syntax tree to inspect")
    try:
        import sqlglot
    except ImportError:
        return WallClockLintResult(False, unavailable_reason="sqlglot is unavailable in the future runtime environment")
    try:
        if getattr(sqlglot, "__version__", None) != review.sqlglot_version:
            raise _Unavailable("Installed parser release differs from the actual reviewed release")
        parse = getattr(sqlglot, "parse", None)
        level = getattr(getattr(getattr(sqlglot, "errors", None), "ErrorLevel", None), "RAISE", None)
        exp = getattr(sqlglot, "exp", None)
        if not callable(parse) or level is None or exp is None:
            raise _Unavailable("Strict PostgreSQL parse capabilities are unavailable")
        expression = _class(exp, "Expression")
        current_classes = tuple(_class(exp, name, expression) for name in ("CurrentDate", "CurrentTimestamp", "CurrentTime"))
        local_classes = tuple(candidate for name in ("Localtimestamp", "LocalTimestamp") if isinstance(candidate := getattr(exp, name, None), type) and issubclass(candidate, expression))
        if not local_classes:
            raise _Unavailable("Reviewed local-timestamp AST representation is unavailable")
        cast_class = _class(exp, "Cast", expression)
        try_cast = getattr(exp, "TryCast", None)
        cast_classes = (cast_class,) + ((try_cast,) if isinstance(try_cast, type) and issubclass(try_cast, expression) else ())
        literal_class = _class(exp, "Literal", expression)
        datatype_class = _class(exp, "DataType", expression)
        anonymous_class = _class(exp, "Anonymous", expression)
        function_class = _class(exp, "Func", expression)
        statements = parse(sql, read="postgres", error_level=level)
        if not isinstance(statements, list) or len(statements) != 1 or not isinstance(statements[0], expression):
            raise _Unavailable("Wall-clock lint requires exactly one parsed nonempty candidate statement")
        prohibited_functions = {"clock_timestamp", "timeofday", "age", "statement_timestamp", "transaction_timestamp", "now"}
        magic_dates = {"now", "today", "tomorrow", "yesterday"}
        pending = [statements[0]]
        seen: set[int] = set()
        violations: list[WallClockViolation] = []
        while pending:
            node = pending.pop()
            if not isinstance(node, expression) or id(node) in seen:
                raise _Unavailable("AST is not a finite singly owned expression tree")
            seen.add(id(node))
            if len(seen) > max_ast_nodes:
                raise _Unavailable("Wall-clock lint AST bound was exceeded")
            args = _args(node)
            kind = type(node).__name__
            if isinstance(node, current_classes + local_classes):
                violations.append(WallClockViolation(kind, "Implicit current date/time"))
            if isinstance(node, cast_classes):
                value, target = args.get("this"), args.get("to")
                if isinstance(value, literal_class):
                    literal_args = _args(value)
                    is_string = literal_args.get("is_string")
                    text = literal_args.get("this")
                    if is_string is True and isinstance(text, str) and text.strip().casefold() in magic_dates:
                        if not isinstance(target, datatype_class):
                            raise _Unavailable("Magic-date cast has an unreviewed target type layout")
                        target_name = _type_name(target)
                        if target_name == "DATE" or target_name.startswith("TIMESTAMP") or target_name == "DATETIME":
                            violations.append(WallClockViolation(kind, "Relative date/timestamp string cast"))
            if isinstance(node, anonymous_class):
                name = args.get("this")
                if not isinstance(name, str):
                    raise _Unavailable("Anonymous function name has an unreviewed representation")
                if name.casefold() in prohibited_functions:
                    violations.append(WallClockViolation(kind, "Prohibited wall-clock function"))
            elif isinstance(node, function_class) and not isinstance(node, current_classes + local_classes):
                # Future parser releases may promote anonymous calls to a
                # dedicated Func class; guarded inspection preserves coverage.
                sql_name = getattr(node, "sql_name", None)
                if not callable(sql_name):
                    raise _Unavailable("Function name capability is unavailable")
                name = sql_name()
                if not isinstance(name, str):
                    raise _Unavailable("Function SQL name is not reviewed scalar text")
                if name.casefold() in prohibited_functions:
                    violations.append(WallClockViolation(kind, "Prohibited wall-clock function"))
            for value in args.values():
                if isinstance(value, expression):
                    pending.append(value)
                elif isinstance(value, (tuple, list)):
                    pending.extend(item for item in value if isinstance(item, expression))
        return WallClockLintResult(True, tuple(violations))
    except Exception as exc:
        detail = str(exc) if isinstance(exc, _Unavailable) else f"Candidate AST inspection is unavailable: {type(exc).__name__}"
        return WallClockLintResult(False, unavailable_reason=detail)

