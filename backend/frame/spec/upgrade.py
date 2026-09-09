"""Read-time spec upgraders.

The renderer must render every spec version it has ever published. Upgrading at
read time keeps that promise without ever running a batch migration against a
table of rows people depend on: old rows stay as they were written, and the
upgrade chain runs on the way out.

Adding a version:
  1. bump SPEC_VERSION in schema.py
  2. register an upgrader from the previous version here
  3. write a test that loads a fixture of the old shape
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from frame.spec.schema import SPEC_VERSION

Upgrader = Callable[[dict[str, Any]], dict[str, Any]]

_UPGRADERS: dict[int, Upgrader] = {}


def upgrader(from_version: int) -> Callable[[Upgrader], Upgrader]:
    def register(fn: Upgrader) -> Upgrader:
        _UPGRADERS[from_version] = fn
        return fn

    return register


def upgrade_to_latest(raw: dict[str, Any]) -> dict[str, Any]:
    """Walk a raw spec document up to the current schema version."""
    doc = dict(raw)
    version = int(doc.get("specVersion", doc.get("spec_version", 1)))

    while version < SPEC_VERSION:
        step = _UPGRADERS.get(version)
        if step is None:
            raise ValueError(
                f"no upgrader registered from spec version {version} — "
                f"cannot read this spec at version {SPEC_VERSION}"
            )
        doc = step(doc)
        version = int(doc.get("specVersion", version + 1))

    if version > SPEC_VERSION:
        raise ValueError(
            f"spec version {version} is newer than this runtime understands "
            f"({SPEC_VERSION}); deploy the runtime before the spec"
        )
    return doc
