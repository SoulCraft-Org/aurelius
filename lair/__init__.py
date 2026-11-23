"""The Lair: a deterministic simulator for Aurelius workers."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_spec(path=None):
    """Read the one spec; default is spec/aurelius.json at the repo root."""
    with open(path or ROOT / "spec" / "aurelius.json", encoding="utf-8") as f:
        return json.load(f)
