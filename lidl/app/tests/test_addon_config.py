"""Spójność wersji i opcji add-onu (config.yaml ↔ pyproject ↔ pakiet ↔ requirements)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from lidl import __version__

ADDON = Path(__file__).resolve().parents[2]


def test_versions_match() -> None:
    config = yaml.safe_load((ADDON / "config.yaml").read_text())
    pyproject = (ADDON / "app" / "pyproject.toml").read_text()
    assert config["version"] == __version__
    assert re.search(rf'^version = "{re.escape(__version__)}"$', pyproject, re.M)


def test_options_have_schema_and_translations() -> None:
    config = yaml.safe_load((ADDON / "config.yaml").read_text())
    assert set(config["options"]) == set(config["schema"])
    for lang in ("pl", "en"):
        tr = yaml.safe_load((ADDON / "translations" / f"{lang}.yaml").read_text())
        assert set(tr["configuration"]) == set(config["options"])


def test_requirements_are_pinned() -> None:
    lines = [
        ln for ln in (ADDON / "requirements.txt").read_text().splitlines() if ln and not ln.startswith("#")
    ]
    assert lines and all("==" in ln for ln in lines)
