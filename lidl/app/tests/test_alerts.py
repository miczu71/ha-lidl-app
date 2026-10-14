from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lidl import alerts, notify
from lidl.history import History
from lidl.web.status import Problem

SESSION = Problem(
    "session:osoba-2", "system", "Sesja konta Osoba 2 wygasła — kupony stoją", "Zaloguj", "/konta"
)
LEAFLET = Problem("leaflet:f1", "leaflet", "Gazetka 13 paź: odłożone paczki 2 z 15")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []

    async def send(
        session: Any, message: tuple[str, str], *, tag: str = notify.TAG, service: str = ""
    ) -> bool:
        out.append((service, tag, *message))
        return True

    monkeypatch.setattr(notify, "send", send)
    return out


async def test_each_problem_is_pushed_once_until_it_recovers(tmp_path: Path, sent: list[Any]) -> None:
    h = History(tmp_path / "h.db")
    await alerts.check(None, h, [SESSION], "admin_phone")  # type: ignore[arg-type]
    await alerts.check(None, h, [SESSION, LEAFLET], "admin_phone")  # type: ignore[arg-type]
    assert [(s[0], s[1]) for s in sent] == [("admin_phone", notify.TAG_ALERT)] * 2
    assert "Osoba 2" in sent[0][3] and "Gazetka" in sent[1][3] and "Osoba 2" not in sent[1][3]
    await alerts.check(None, h, [LEAFLET], "admin_phone")  # type: ignore[arg-type]  # sesja wróciła
    await alerts.check(None, h, [SESSION, LEAFLET], "admin_phone")  # type: ignore[arg-type]
    assert len(sent) == 3 and "Osoba 2" in sent[2][3]


async def test_without_service_only_the_dot_no_push(tmp_path: Path, sent: list[Any]) -> None:
    h = History(tmp_path / "h.db")
    await alerts.check(None, h, [SESSION], "")  # type: ignore[arg-type]
    assert sent == []
