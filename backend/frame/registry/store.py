"""L4 — the spec registry.

A dashboard is a row. Adding one is an INSERT; editing one is an UPDATE;
nothing builds and nothing deploys. This implementation is file-backed so the
repo runs with no database, and the interface is the one a Postgres-backed
store implements unchanged.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from frame.config import SPECS_DIR
from frame.spec.schema import DashboardSpec
from frame.spec.upgrade import upgrade_to_latest


class SpecRegistry:
    def __init__(self, directory: Path | None = None) -> None:
        self._dir = Path(directory or SPECS_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Parsed specs, keyed by path and invalidated on mtime. A dashboard
        # load asks for the same spec once per block; re-reading and
        # re-validating the document a dozen times per load is pure waste, and
        # a stat() still keeps "edit the file, reload the page" working.
        self._parsed: dict[str, tuple[int, DashboardSpec]] = {}

    def _path(self, spec_id: str) -> Path:
        if "/" in spec_id or "\\" in spec_id or spec_id.startswith("."):
            raise ValueError(f"illegal spec id {spec_id!r}")
        return self._dir / f"{spec_id}.json"

    def get(self, spec_id: str) -> DashboardSpec:
        path = self._path(spec_id)
        try:
            mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            self._parsed.pop(spec_id, None)
            raise KeyError(spec_id) from None

        cached = self._parsed.get(spec_id)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        raw = json.loads(path.read_text(encoding="utf-8"))
        # Old rows stay as written; the upgrade chain runs on the way out.
        spec = DashboardSpec.model_validate(upgrade_to_latest(raw))
        self._parsed[spec_id] = (mtime, spec)
        return spec

    def put(self, spec: DashboardSpec) -> DashboardSpec:
        with self._lock:
            payload = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
            self._path(spec.id).write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
        return spec

    def delete(self, spec_id: str) -> None:
        path = self._path(spec_id)
        if path.exists():
            path.unlink()
        self._parsed.pop(spec_id, None)

    def list(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                spec = self.get(path.stem)
            except Exception as exc:  # a bad row must not break the index
                out.append({"id": path.stem, "error": str(exc)})
                continue
            out.append(
                {
                    "id": spec.id,
                    "title": spec.title,
                    "description": spec.description,
                    "model": spec.model,
                    "freshness": spec.freshness.value,
                    "owner": spec.owner,
                    "tags": spec.tags,
                    "blocks": len(spec.blocks),
                    "specVersion": spec.spec_version,
                }
            )
        return out


registry = SpecRegistry()
