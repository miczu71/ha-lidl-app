"""Linia Biedronki w porannym powiadomieniu (E28.5.3): vouchery kończące się w ≤3 dni, licznik ofert."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from lidl import notify
from lidl.chain_savings import Saving, local_date
from lidl.history import History

TODAY = date(2026, 11, 19)


def _rows(tmp_path: Path, rows: list[Saving]) -> list:  # type: ignore[type-arg]
    h = History(tmp_path / "h.db")
    h.savings_replace("b", {r.kind for r in rows}, rows)
    return h.savings_list()


def _v(ext: str, name: str, end: str | None) -> Saving:
    return Saving("voucher", ext, name, None, None, None, end, {})


def _o(ext: str) -> Saving:
    return Saving("offer", ext, f"Oferta {ext}", 1.0, 2.0, None, "2026-11-25T22:59:59Z", {})


def test_local_date_polish_time_and_garbage() -> None:
    assert local_date("2026-11-21T22:59:59Z") == date(2026, 11, 21)
    assert local_date("2026-11-21T23:00:00Z") == date(2026, 11, 22)  # północ w Polsce
    assert local_date("nonsens") is None and local_date(None) is None


def test_no_line_without_urgent_voucher(tmp_path: Path) -> None:
    rows = _rows(tmp_path, [_v("1", "Rabat", "2026-11-30T22:59:59Z"), _o("a")])
    assert notify.bdr_line(rows, TODAY) is None


def test_line_lists_urgent_vouchers_and_offer_count(tmp_path: Path) -> None:
    rows = _rows(
        tmp_path,
        [
            _v("1", "Rabat 5 zł", "2026-11-21T22:59:59Z"),
            _v("2", "Stary", "2026-11-10T22:59:59Z"),
            _v("3", "Dziś", "2026-11-19T22:59:59Z"),
            _o("a"),
            _o("b"),
        ],
    )
    line = notify.bdr_line(rows, TODAY)
    assert line == "Biedronka: Dziś (dziś) · Rabat 5 zł (za 2 dni) · 2 oferty Tylko dla Ciebie"
    assert "Stary" not in (line or "")


def test_line_without_offers(tmp_path: Path) -> None:
    rows = _rows(tmp_path, [_v("1", "Rabat", "2026-11-20T22:59:59Z")])
    assert notify.bdr_line(rows, TODAY) == "Biedronka: Rabat (jutro)"


def test_compose_adds_line_and_sends_alone() -> None:
    line = "Biedronka: Rabat (jutro)"
    alone = notify.compose({}, None, dry_run=False, today=TODAY, bdr=line)
    assert alone == ("Lidl: voucher Biedronki wygasa", line)
    assert notify.compose({}, None, dry_run=False, today=TODAY) is None


def test_compose_shakeomat() -> None:
    from lidl.chain_savings import ShakeResult

    labels = {"b": "Osoba 2"}
    assert notify.compose_shakeomat([], labels) is None
    assert notify.compose_shakeomat([ShakeResult("b")], labels) is None
    assert notify.compose_shakeomat([ShakeResult("b", 1)], labels) == (
        "Biedronka: Shakeomat odsłonięty",
        "Osoba 2: odsłonięto 1",
    )
    title, body = notify.compose_shakeomat([ShakeResult("b", 0, ["LidlPlusError: http_409"])], labels) or (
        "",
        "",
    )
    assert "nie wszystko" in title and "http_409" in body
