"""Lecture de twin/config/defaults.yaml (chemin surchargeable par TWIN_DEFAULTS)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULTS_PATH = Path(os.environ.get("TWIN_DEFAULTS", Path(__file__).resolve().parent / "config" / "defaults.yaml"))


@lru_cache(maxsize=1)
def raw_defaults() -> dict:
    with open(DEFAULTS_PATH) as f:
        return yaml.safe_load(f)


def value(*path: str) -> Any:
    """Valeur d'une entrée ``{value: ..., source: ...}`` ou d'une valeur simple."""
    node: Any = raw_defaults()
    for key in path:
        node = node[key]
    return node["value"] if isinstance(node, dict) and "value" in node else node


def entry(*path: str) -> dict:
    node: Any = raw_defaults()
    for key in path:
        node = node[key]
    return node
