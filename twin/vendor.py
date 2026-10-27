"""Accès en lecture seule au code SustainDC cloné dans vendor/sustaindc.

Le code vendor n'est jamais modifié : on l'importe tel quel en plaçant sa racine
en tête de sys.path (ses modules s'importent entre eux via ``utils.*`` et ``envs.*``).
"""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = Path(os.environ.get("SUSTAINDC_ROOT", REPO_ROOT / "vendor" / "sustaindc"))
VENDOR_COMMIT = "a92b475"


def ensure_vendor_path() -> Path:
    if not (VENDOR_ROOT / "envs" / "datacenter.py").exists():
        raise RuntimeError(
            f"SustainDC introuvable dans {VENDOR_ROOT}. Lancer `make vendor` "
            "(git clone https://github.com/HewlettPackard/dc-rl vendor/sustaindc)."
        )
    root = str(VENDOR_ROOT)
    if sys.path[:1] != [root]:
        if root in sys.path:
            sys.path.remove(root)
        sys.path.insert(0, root)
    return VENDOR_ROOT


@lru_cache(maxsize=1)
def vendor_dc_config() -> dict:
    """Paramètres physiques par défaut de SustainDC (utils/dc_config.json)."""
    with open(ensure_vendor_path() / "utils" / "dc_config.json") as f:
        return json.load(f)


def vendor_data_dir() -> Path:
    return ensure_vendor_path() / "data"
