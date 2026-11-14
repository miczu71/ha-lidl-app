from __future__ import annotations

import json
from pathlib import Path

import pytest

from lidl.settings import _countries, load_settings


def test_countries_normalises_and_drops_pl_duplicates_and_junk() -> None:
    assert _countries(["cz", " it ", "PL", "CZ", "xyz", "1a"]) == ("CZ", "IT")


def test_countries_non_list_is_empty() -> None:
    assert _countries("CZ") == ()
    assert _countries(None) == ()


def test_load_settings_reads_extra_countries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"extra_countries": ["cz", "IT", "PL"]}), encoding="utf-8")
    monkeypatch.setenv("LIDL_OPTIONS_PATH", str(options))
    assert load_settings().extra_countries == ("CZ", "IT")
