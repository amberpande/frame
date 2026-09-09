"""Merging a dashboard's own calculations into the model, for one query.

A spec may define calculated metrics. They behave exactly like derived metrics
in the semantic model — same compiler, same grain rules, same guards — but they
live and die with the dashboard and never enter the shared namespace.

The overlay is built per request and only when the spec actually declares
calculations. That matters for the cache: an overlaid model has a different
fingerprint, so a dashboard with local metrics keys separately, while every
dashboard without them keeps sharing cache entries as before.
"""

from __future__ import annotations

from frame.semantic.expr import ExpressionError, ParsedExpression, validate_expression
from frame.semantic.model import Metric, SemanticModel


def source_map(model: SemanticModel) -> dict[str, set[str]]:
    """Every metric, mapped to the source tables it ultimately reads."""
    out: dict[str, set[str]] = {}
    for metric in model.metrics:
        out[metric.name] = {b.source for b in model.base_metrics(metric.name) if b.source}
    return out


def check_single_source(sources_of: dict[str, set[str]], parsed: ParsedExpression) -> set[str]:
    """Refuse a calculation whose inputs live in different tables.

    The compiler cannot join across sources, so such a calculation would
    validate and then fail on first render. Catching it while the formula is
    being typed is the difference between a clear message and a mystery.

    Takes a name → sources map rather than the model, so a calculation that
    builds on an earlier calculation in the same spec resolves correctly.
    """
    used: dict[str, list[str]] = {}
    for ref in parsed.references:
        for source in sources_of.get(ref, set()):
            used.setdefault(source, []).append(ref)

    if len(used) > 1:
        raise ExpressionError(
            "multi_source_calculation",
            "this formula combines metrics from different tables "
            f"({', '.join(sorted(used))}), which cannot be computed in one "
            "query. Declared join paths are not supported yet.",
            sources=sorted(used),
            metrics={k: sorted(set(v)) for k, v in used.items()},
        )
    return set(used)


def overlay(model: SemanticModel, calculations: list) -> SemanticModel:
    """Return `model` plus the spec's calculated metrics.

    Raises ExpressionError if a formula is not permitted, references an unknown
    metric, shadows a governed one, or spans two sources.
    """
    if not calculations:
        return model

    known = {m.name for m in model.metrics}
    sources_of = source_map(model)
    payload = model.model_dump(mode="json")

    for calc in calculations:
        if calc.name in known:
            raise ExpressionError(
                "shadows_model_metric",
                f"{calc.name!r} already exists in model {model.name!r}; "
                "a dashboard calculation may not redefine a governed metric",
                metric=calc.name,
            )

        # Validated against what is known *so far*, so a calculation may build
        # on an earlier one in the same spec but never on a later one.
        parsed = validate_expression(calc.expr, known)
        sources_of[calc.name] = check_single_source(sources_of, parsed)

        payload["metrics"].append(
            Metric(
                name=calc.name,
                label=calc.label,
                kind="derived",
                expr=calc.expr,
                format=calc.format,
                direction=calc.direction,
                note=calc.description,
                # Not governed, and honest about it. `owner` records where it
                # came from so a promotion candidate can be traced back.
                curated=False,
                owner="dashboard",
                tests=[],
            ).model_dump(mode="json")
        )
        known.add(calc.name)

    # Re-validated as a whole, so grain intersection and reference checks run
    # exactly as they would for a hand-written model.
    return SemanticModel.model_validate(payload)
