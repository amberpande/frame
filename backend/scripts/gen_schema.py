"""Emit JSON Schema for the spec, from the Pydantic definition.

One definition, four consumers. This is the fourth: an editor or a coding
agent gets completion and inline validation while writing a spec, instead of
discovering a mistake as a 422 after publishing.

    python scripts_gen_schema.py
"""
from __future__ import annotations

import json
from pathlib import Path

from frame.spec.schema import SPEC_VERSION, DashboardSpec

OUT = Path(__file__).resolve().parent / "schemas" / "spec.schema.json"


def main() -> None:
    schema = DashboardSpec.model_json_schema(by_alias=True, mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://frame.internal/schemas/spec.schema.json"
    schema["title"] = f"Frame dashboard spec (v{SPEC_VERSION})"
    schema["description"] = (
        "A dashboard, as data. Metrics and dimensions must exist in the semantic "
        "model named by `model`; POST /api/v1/validate checks a query without "
        "reading a row. No spec may contain SQL."
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(schema.get('$defs', {}))} definitions)")


if __name__ == "__main__":
    main()
