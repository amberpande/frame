from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from frame.config import MODELS_DIR
from frame.semantic.model import SemanticModel


def _load_file(path: Path) -> SemanticModel:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    # `x-` keys exist only to host YAML anchors (&grain) that the rest of the
    # file reuses. They are scaffolding, not model content, so they are dropped
    # before validation — everything else stays strictly forbidden, because a
    # typo'd key in a semantic model is a silently missing definition.
    raw = {k: v for k, v in raw.items() if not k.startswith("x-")}
    return SemanticModel.model_validate(raw)


@lru_cache(maxsize=32)
def get_model(name: str) -> SemanticModel:
    path = MODELS_DIR / f"{name}.yml"
    if not path.exists():
        path = MODELS_DIR / f"{name}.yaml"
    if not path.exists():
        raise KeyError(f"no semantic model named {name!r} in {MODELS_DIR}")
    return _load_file(path)


def list_models() -> list[str]:
    if not MODELS_DIR.exists():
        return []
    return sorted(p.stem for p in MODELS_DIR.iterdir() if p.suffix in {".yml", ".yaml"})


def reload_models() -> None:
    get_model.cache_clear()
