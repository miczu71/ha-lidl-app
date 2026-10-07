from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from lidl.accounts import AccountStore, slugify


def test_slugify_strips_diacritics_and_symbols() -> None:
    assert slugify("Żaneta Nowak!") == "zaneta-nowak"
    with pytest.raises(ValueError):
        slugify("!!!")


def test_create_gives_unique_slugs(tmp_path: Path) -> None:
    store = AccountStore(tmp_path)
    a = store.create("Osoba 1")
    b = store.create("Osoba 1")
    assert (a.slug, b.slug) == ("osoba-1", "osoba-1-2")
    assert [x.slug for x in store.list()] == ["osoba-1", "osoba-1-2"]


def test_tokens_are_private_and_replace_atomically(tmp_path: Path) -> None:
    store = AccountStore(tmp_path / "accounts")
    acc = store.create("Osoba 1")
    assert not store.get(acc.slug).connected
    store.save_tokens(acc.slug, {"access_token": "a1", "refresh_token": "r1"})
    store.save_tokens(acc.slug, {"access_token": "a2", "refresh_token": "r2"})
    path = tmp_path / "accounts" / "osoba-1.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["refresh_token"] == "r2"
    assert not list(path.parent.glob("*.tmp"))
    assert store.get(acc.slug).connected


def test_delete_and_bad_slug(tmp_path: Path) -> None:
    store = AccountStore(tmp_path)
    acc = store.create("Osoba 1")
    store.delete(acc.slug)
    assert store.list() == []
    for bad in ("../x", "A", ""):
        with pytest.raises(KeyError):
            store.get(bad)
