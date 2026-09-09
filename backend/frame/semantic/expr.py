"""Validating a calculated-metric expression.

This is a security boundary, not a convenience check. A calculated metric's
expression ends up inside the SQL the compiler emits, so anything this function
lets through is something a dashboard author can put in a query. The rule is
therefore an allow-list, not a deny-list:

    permitted   {metric.name} references, numbers, + - * / ( ) ,
                and a short list of scalar functions
    rejected    everything else, including bare identifiers

The bare-identifier rule is the one that matters. `revenue` on its own would be
a column reference — it would compile, it would read a column nobody modelled,
and it would silently escape the semantic layer. Only `{revenue}` is a metric;
`revenue` is an error.

What this cannot express is deliberate: no table names, no joins, no
subqueries, no string literals, no aggregate functions. A calculation that
needs any of those is a *measure*, and a measure belongs in the model where it
gets a grain, an owner and a test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Scalar, null-safe, and side-effect free. Aggregates are absent on purpose:
# the operands are already aggregated by the time the expression is evaluated,
# so SUM(...) here would be a second, meaningless aggregation.
ALLOWED_FUNCTIONS = frozenset(
    {
        "NULLIF",
        "COALESCE",
        "ABS",
        "ROUND",
        "FLOOR",
        "CEIL",
        "CEILING",
        "GREATEST",
        "LEAST",
        "POWER",
        "SQRT",
        "LN",
        "LOG",
        "EXP",
        "SIGN",
        "MOD",
    }
)

_TOKEN = re.compile(
    r"""
    (?P<ref>\{[^{}]*\})                 # {metric.name} or {metric@stat}
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>[+\-*/(),])
  | (?P<space>\s+)
  | (?P<bad>.)
    """,
    re.VERBOSE,
)

_REF_BODY = re.compile(r"^\{([a-zA-Z0-9_.]+)(?:@([a-zA-Z0-9_]+))?\}$")


class ExpressionError(ValueError):
    """Carries a machine-readable reason, like every other refusal."""

    def __init__(self, reason: str, detail: str, **context: object) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.context = context

    def to_dict(self) -> dict:
        return {"reason": self.reason, "detail": self.detail, **self.context}


@dataclass(frozen=True)
class ParsedExpression:
    references: tuple[str, ...]
    functions: tuple[str, ...]


def validate_expression(expr: str, known_metrics: set[str]) -> ParsedExpression:
    """Parse and check an expression. Raises ExpressionError, or returns what
    it references."""
    if not expr or not expr.strip():
        raise ExpressionError("empty_expression", "the formula is empty")
    if len(expr) > 1000:
        raise ExpressionError(
            "expression_too_long", f"formula is {len(expr)} characters; the limit is 1000"
        )

    references: list[str] = []
    functions: list[str] = []
    depth = 0
    previous: str | None = None

    for match in _TOKEN.finditer(expr):
        kind = match.lastgroup
        text = match.group()

        if kind == "space":
            continue

        if kind == "bad":
            raise ExpressionError(
                "illegal_character",
                f"{text!r} is not allowed in a formula. Use metric references "
                "like {metric.name}, numbers, + - * / and parentheses.",
                character=text,
                position=match.start(),
            )

        if kind == "ref":
            parsed = _REF_BODY.match(text)
            if not parsed:
                raise ExpressionError(
                    "malformed_reference",
                    f"{text} is not a valid metric reference; expected {{metric.name}}",
                    reference=text,
                )
            name = parsed.group(1)
            if name not in known_metrics:
                raise ExpressionError(
                    "unknown_metric",
                    f"{name!r} is not a metric in this model",
                    metric=name,
                    available=sorted(known_metrics),
                )
            references.append(name)

        elif kind == "ident":
            # An identifier is only ever a function name, and only immediately
            # before "(". Anything else is a column reference trying to escape.
            rest = expr[match.end() :].lstrip()
            if not rest.startswith("("):
                raise ExpressionError(
                    "bare_identifier",
                    f"{text!r} looks like a column name. Only metric references are "
                    f"allowed - write {{{text}}} if you meant the metric, or define "
                    "a measure in the semantic model if you meant a column.",
                    identifier=text,
                )
            if text.upper() not in ALLOWED_FUNCTIONS:
                raise ExpressionError(
                    "function_not_allowed",
                    f"{text}() is not available in a formula",
                    function=text,
                    allowed=sorted(ALLOWED_FUNCTIONS),
                )
            functions.append(text.upper())

        elif kind == "op":
            if text == "(":
                depth += 1
            elif text == ")":
                depth -= 1
                if depth < 0:
                    raise ExpressionError(
                        "unbalanced_parentheses", "a closing parenthesis has no opener"
                    )
            elif text in "+-*/" and previous in (None, "+", "-", "*", "/", "(",):
                # Unary minus is fine; two operators in a row are not.
                if not (text == "-" and previous in (None, "(", "+", "-", "*", "/")):
                    raise ExpressionError(
                        "malformed_expression",
                        f"{previous!r} followed by {text!r} is not a valid formula",
                    )

        previous = text

    if depth != 0:
        raise ExpressionError(
            "unbalanced_parentheses", f"{depth} parenthesis(es) left unclosed"
        )
    if not references:
        raise ExpressionError(
            "no_metric_reference",
            "a formula must reference at least one metric, like {exception.count}",
        )
    if previous in ("+", "-", "*", "/"):
        raise ExpressionError(
            "malformed_expression", f"the formula ends with {previous!r}"
        )

    return ParsedExpression(
        references=tuple(dict.fromkeys(references)), functions=tuple(dict.fromkeys(functions))
    )
