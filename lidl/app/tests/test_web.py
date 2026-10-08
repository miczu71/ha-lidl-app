from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from lidl import __version__
from lidl.client.exceptions import LidlPlusAuthError
from lidl.history import CouponCandidate, PriceChange
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.rewards import CouponPlus, Goal, Rewards, ScratchCard
from lidl.service import LidlService
from lidl.settings import Settings
from lidl.web import prices
from lidl.web.app import create_app
from lidl.web.prices import top_changes
from lidl.web.products import coupon_rows, effect_view, reward_cards


def test_index_empty_and_no_store(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Brak kont" in r.text and f"?v={__version__}" in r.text
    assert r.headers["cache-control"] == "no-store"


def test_static_is_immutable(client: TestClient) -> None:
    r = client.get("/static/app.css")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]


def test_add_account_then_login_page_has_pkce_url(client: TestClient) -> None:
    r = client.post(
        "/accounts", data={"label": "Osoba 1"}, headers={"x-ingress-path": "/api/hassio_ingress/abc"}
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/api/hassio_ingress/abc/accounts/osoba-1/login"
    page = client.get("/accounts/osoba-1/login")
    assert "accounts.lidl.com/connect/authorize" in page.text
    assert "code_challenge_method=S256" in page.text
    assert "Osoba 1" in client.get("/").text


def test_failed_login_shows_error_and_fresh_url(client: TestClient, monkeypatch) -> None:
    client.post("/accounts", data={"label": "Osoba 1"})

    async def reject(self: LidlService, slug: str, pasted: str) -> None:
        raise LidlPlusAuthError("token_rejected")

    monkeypatch.setattr(LidlService, "finish_login", reject)
    r = client.post("/accounts/osoba-1/login", data={"pasted": "com.lidlplus.app://callback?code=SECRETCODE"})
    assert r.status_code == 200
    assert "Zaloguj się od nowa" in r.text
    assert "SECRETCODE" not in r.text


def test_successful_login_redirects(client: TestClient, monkeypatch) -> None:
    client.post("/accounts", data={"label": "Osoba 1"})

    async def ok(self: LidlService, slug: str, pasted: str) -> None:
        return None

    monkeypatch.setattr(LidlService, "finish_login", ok)
    r = client.post("/accounts/osoba-1/login", data={"pasted": "x"})
    assert (r.status_code, r.headers["location"]) == (303, "/?m=connected")


def test_delete_removes_account(client: TestClient) -> None:
    client.post("/accounts", data={"label": "Osoba 1"})
    client.post("/accounts/osoba-1/delete")
    assert "Brak kont" in client.get("/").text


def test_non_ingress_peer_is_rejected(settings: Settings) -> None:
    prod = Settings(data_dir=settings.data_dir, log_level="info", dev=False)
    with TestClient(create_app(prod)) as c:
        assert c.get("/").status_code == 403


# --- Produkty (E2.2) ---------------------------------------------------------


def _seed(client: TestClient, days: tuple[str, ...] = ("2026-09-02", "2026-10-02")) -> None:
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets(
        "osoba-1",
        [
            {"id": f"t{i}", "date": f"{d}T10:00:00+00:00", "totalAmount": 20.0, "savings": 2.5}
            for i, d in enumerate(days)
        ],
    )
    for i, _ in enumerate(days):
        history.save_detail(
            f"t{i}",
            "Sklep X",
            ParsedReceipt(
                items=[
                    ReceiptItem("111", "Produkt A", 2, 5.0, 10.0, discount=-2.0, coupon=-1.0),
                    ReceiptItem("222", "Produkt B", 1, 8.0, 8.0),
                ],
                deposit_charged=5.0 if i == 0 else 4.0,
                deposit_refunded=1.0 if i == 0 else 0.0,
            ),
        )


def _connect(client: TestClient, label: str = "Osoba 1") -> str:
    store = client.app.state.service.store  # type: ignore[attr-defined]
    slug = store.create(label).slug
    store.save_tokens(slug, {"access_token": "a", "refresh_token": "r"})
    return slug


def test_products_empty_history_offers_import_per_account(client: TestClient) -> None:
    _connect(client)
    client.app.state.service.store.create("Osoba 2")  # type: ignore[attr-defined]
    r = client.get("/produkty")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "Brak historii zakupów" in r.text
    assert 'action="/accounts/osoba-1/history"' in r.text
    assert "/accounts/osoba-2/login" in r.text
    assert "Dotychczasowe oszczędności" not in r.text


def test_products_shows_kpi_chart_and_ranking(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?zakres=all").text
    assert "Dotychczasowe oszczędności" in text and "4,00 zł" in text
    assert "Kupony Lidl Plus" in text and "Promocje" in text and "2,00 zł" in text
    assert "Zapłacono łącznie" in text and "40,00 zł" in text
    assert "Kaucje pobrane" in text and "9,00 zł" in text
    assert "Kaucje zwrócone" in text and "1,00 zł" in text
    assert "wrzesień 2026: 16 zł" in text
    assert "Produkt A" in text and "2 zakupy" in text
    assert 'aria-pressed="true"' in text and "Historia jest aktualna: 2 paragony" in text


def test_products_filters_chart_by_product_and_metric(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?zakres=all&produkt=222&miara=sztuki").text
    assert "wrzesień 2026: 1 szt." in text
    assert 'name="produkt" value="222"' in text and "Produkt: <strong>Produkt B</strong>" in text


def test_products_reversed_range_shows_error_without_chart(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?od=2026-10-01&do=2026-01-01").text
    assert "Data „Od” jest późniejsza niż „Do”" in text
    assert 'role="img"' not in text


def test_products_range_without_purchases_says_so(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?od=2018-01-01&do=2018-03-31").text
    assert "Brak zakupów w tym zakresie" in text and 'role="img"' not in text


def test_products_ranking_limit_and_more_link(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?zakres=all&limit=1").text
    assert "Produkt A" in text and 'aria-label="Pokaż Produkt B na wykresie"' not in text
    assert "limit=26" in text and "Pokaż więcej" in text
    assert "Pokaż więcej" not in client.get("/produkty?zakres=all").text


def test_products_running_import_shows_progress_and_refreshes(client: TestClient) -> None:
    slug = _connect(client)
    _seed(client)
    progress = client.app.state.sync.progress(slug)  # type: ignore[attr-defined]
    progress.running, progress.done, progress.total = True, 120, 334
    text = client.get("/produkty").text
    assert 'aria-valuenow="120"' in text and "120 z 334" in text
    assert 'http-equiv="refresh"' in text


def test_products_failed_import_offers_resume(client: TestClient) -> None:
    slug = _connect(client)
    _seed(client)
    client.app.state.sync.progress(slug).error = "http_429"  # type: ignore[attr-defined]
    text = client.get("/produkty").text
    assert "Import przerwany" in text and 'action="/history/resume"' in text
    assert 'http-equiv="refresh"' not in text


def test_start_history_import_redirects_and_starts_full_sync(client: TestClient, monkeypatch) -> None:
    slug = _connect(client)
    started: list[tuple[str, bool]] = []
    sync = client.app.state.sync  # type: ignore[attr-defined]
    monkeypatch.setattr(sync, "start", lambda s, *, full: started.append((s, full)) or True)
    r = client.post(f"/accounts/{slug}/history", headers={"x-ingress-path": "/i"})
    assert r.status_code == 303 and r.headers["location"] == "/i/produkty"
    assert started == [(slug, True)]


def test_start_history_import_for_unconnected_account_goes_to_accounts(client: TestClient) -> None:
    slug = client.app.state.service.store.create("Osoba 2").slug  # type: ignore[attr-defined]
    r = client.post(f"/accounts/{slug}/history")
    assert r.status_code == 303 and r.headers["location"] == "/?m=expired"


def test_resume_restarts_only_accounts_with_history(client: TestClient, monkeypatch) -> None:
    slug = _connect(client)
    _connect(client, "Osoba 2")
    _seed(client)
    started: list[str] = []
    sync = client.app.state.sync  # type: ignore[attr-defined]
    monkeypatch.setattr(sync, "start", lambda s, *, full: started.append(s) or True)
    r = client.post("/history/resume")
    assert r.status_code == 303 and r.headers["location"] == "/produkty"
    assert started == [slug]


def test_navigation_links_products_and_accounts(client: TestClient) -> None:
    text = client.get("/").text
    assert 'href="/produkty"' in text and 'aria-current="page"' in text


def test_products_warns_about_unparsed_receipts_and_partial_kpi(client: TestClient) -> None:
    _seed(client)
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets(
        "osoba-1", [{"id": "tx", "date": "2026-10-03T10:00:00+00:00", "articlesCount": 4, "totalAmount": 9.0}]
    )
    history.save_detail("tx", "Sklep X", ParsedReceipt())
    history.upsert_tickets(
        "osoba-1", [{"id": "ty", "date": "2026-10-04T10:00:00+00:00", "articlesCount": 2, "totalAmount": 5.0}]
    )
    text = client.get("/produkty?zakres=all").text
    assert "Nie udało się odczytać paragonów: 1" in text
    assert "Liczone z 3 z 4 paragonów" in text
    assert "Kaucje z 2 z 4 paragonów" in text


def test_products_offers_import_for_connected_account_without_history(client: TestClient) -> None:
    _connect(client)
    _connect(client, "Osoba 2")
    _seed(client)
    text = client.get("/produkty").text
    assert 'action="/accounts/osoba-2/history"' in text
    assert 'action="/accounts/osoba-1/history"' not in text


def test_chart_summary_shows_deposits_and_paid_total_for_the_range(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?zakres=all").text
    assert "<strong>32 zł</strong>" in text  # wydatki na pozycje po rabatach
    assert "kaucje pobrane <strong>9 zł</strong>" in text
    assert "zwrócone <strong>1 zł</strong>" in text
    assert "zapłacono łącznie <strong>40 zł</strong>" in text
    one_month = client.get("/produkty?od=2026-09-01&do=2026-09-30").text
    assert "kaucje pobrane <strong>5 zł</strong>" in one_month
    assert "zapłacono łącznie <strong>20 zł</strong>" in one_month


def test_chart_summary_hides_ticket_level_totals_for_one_product_or_pieces(client: TestClient) -> None:
    _seed(client)
    product = client.get("/produkty?zakres=all&produkt=222").text
    assert "kaucje pobrane <strong>" not in product and "na ten produkt" in product
    pieces = client.get("/produkty?zakres=all&miara=sztuki").text
    assert "kaucje pobrane <strong>" not in pieces


def _seed_regular(client: TestClient) -> None:
    """Trzy paragony z ostatniego kwartału: Produkt A (kupon) i Produkt C bez kodu kuponu."""
    history = client.app.state.history  # type: ignore[attr-defined]
    days = [(date.today() - timedelta(days=d)).isoformat() for d in (5, 40, 80)]
    history.upsert_tickets(
        "osoba-1",
        [{"id": f"r{i}", "date": f"{d}T10:00:00+00:00", "totalAmount": 9.0} for i, d in enumerate(days)],
    )
    for i in range(3):
        history.save_detail(
            f"r{i}",
            "Sklep X",
            ParsedReceipt(
                items=[
                    ReceiptItem("111", "Produkt A", 1, 5.0, 5.0, discount=-1.0, coupon=-1.0),
                    ReceiptItem("n:9", "Produkt C", 1, 4.0, 4.0),
                ]
            ),
        )


def test_coupons_lists_regular_products_with_toggles(client: TestClient) -> None:
    _seed_regular(client)
    r = client.get("/kupony")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    text = r.text
    assert "Produkt A" in text and "3 zakupy" in text and "kupon 3×" in text and "3,00 zł" in text
    assert 'role="switch" aria-checked="true"' in text and 'action="/kupony/produkt/111"' in text
    assert "Produkt C" in text and "bez kodu kuponu" in text and 'action="/kupony/produkt/n:9"' not in text
    assert 'href="/kupony"' in text and 'aria-current="page"' in text


def test_coupons_toggle_off_and_on(client: TestClient) -> None:
    _seed_regular(client)
    history = client.app.state.history  # type: ignore[attr-defined]
    r = client.post("/kupony/produkt/111", data={"enabled": "0"})
    assert r.status_code == 303 and r.headers["location"] == "/kupony#p-111"
    assert not any(c.enabled for c in history.coupon_candidates())
    assert 'aria-checked="false"' in client.get("/kupony").text
    client.post("/kupony/produkt/111", data={"enabled": "1"})
    assert {c.art_id for c in history.coupon_candidates() if c.enabled} == {"111"}


def test_star_watches_product_turns_auto_activation_on_and_survives_reload(client: TestClient) -> None:
    _seed_regular(client)
    client.post("/kupony/produkt/111", data={"enabled": "0"})
    text = client.get("/kupony").text
    assert 'aria-pressed="false" aria-label="Obserwuj: Produkt A"' in text
    assert "<dt>Obserwowane</dt><dd>0</dd>" in text
    assert 'action="/kupony/produkt/n:9/obserwuj"' not in text  # bez kodu kuponu nie ma gwiazdki
    r = client.post("/kupony/produkt/111/obserwuj", data={"on": "1"})
    assert r.status_code == 303 and r.headers["location"] == "/kupony#p-111"
    text = client.get("/kupony").text
    assert 'aria-pressed="true" aria-label="Obserwuj: Produkt A"' in text and 'aria-checked="true"' in text
    assert "<dt>Obserwowane</dt><dd>1</dd>" in text
    client.post("/kupony/produkt/111/obserwuj", data={"on": "0"})
    assert client.app.state.history.watched_codes() == set()  # type: ignore[attr-defined]


def test_watched_products_come_first_in_their_ranking_order() -> None:
    def cand(art_id: str, watched: bool) -> CouponCandidate:
        return CouponCandidate(art_id, art_id, 3, "2026-10-01", 0, 0.0, 0.0, True, True, watched)

    rows = coupon_rows([cand("a", False), cand("b", True), cand("c", False), cand("d", True)])
    assert [r["id"] for r in rows] == ["b", "d", "a", "c"]


def test_coupons_without_regular_products_says_why(client: TestClient) -> None:
    text = client.get("/kupony").text
    assert "Za mało historii" in text and 'role="switch"' not in text


def _seed_coupons(client: TestClient) -> None:
    from datetime import UTC, datetime

    from lidl.coupons import parse_coupons

    _connect(client)
    now = datetime.now(UTC)
    day = timedelta(days=1)

    def promo(pid: str, title: str, start: datetime, active: bool = False) -> dict[str, object]:
        return {
            "id": pid, "promotionId": pid, "title": title, "discount": {"title": "-30%"},
            "validity": {"start": start.isoformat(), "end": (now + 3 * day).isoformat()},
            "isActivated": active, "articleIds": [],
        }  # fmt: skip

    payload = {
        "sections": [
            {
                "name": "AllStores",
                "promotions": [
                    promo("a", "Kupon aktywny", now - day, active=True),
                    promo("b", "Kupon do aktywacji", now - day),
                    promo("c", "Kupon nadchodzący", now + day),
                ],
            }
        ]
    }
    history = client.app.state.history  # type: ignore[attr-defined]
    history.save_coupons("osoba-1", parse_coupons(payload), now.isoformat())
    history.set_coupon_statuses("osoba-1", [("b", "would", None)])


def test_coupons_page_lists_current_coupons_per_account(client: TestClient) -> None:
    _seed_coupons(client)
    text = client.get("/kupony").text
    assert "Kupony w tym tygodniu" in text and "Osoba 1" in text
    assert "Kupon aktywny" in text and "Aktywny" in text
    assert "Kupon do aktywacji" in text and "Aktywowałbym" in text
    assert 'action="/kupony/osoba-1/b/aktywuj"' in text
    assert "Kupon nadchodzący" in text and 'action="/kupony/osoba-1/c/aktywuj"' not in text
    assert "Tryb próbny" in text and 'action="/kupony/sprawdz"' in text


def test_manual_activation_redirects_back(client: TestClient, monkeypatch) -> None:
    _seed_coupons(client)
    calls: list[tuple[str, str]] = []

    async def activate_one(slug: str, promotion_id: str) -> bool:
        calls.append((slug, promotion_id))
        return True

    monkeypatch.setattr(client.app.state.runner, "activate_one", activate_one)  # type: ignore[attr-defined]
    r = client.post("/kupony/osoba-1/b/aktywuj")
    assert r.status_code == 303 and r.headers["location"] == "/kupony#kupony-osoba-1"
    assert calls == [("osoba-1", "b")]


def test_check_now_starts_coupon_run_once(client: TestClient, monkeypatch) -> None:
    started: list[bool] = []
    job = client.app.state.job  # type: ignore[attr-defined]
    monkeypatch.setattr(job, "start_coupons", lambda: started.append(True) or True)
    r = client.post("/kupony/sprawdz")
    assert r.status_code == 303 and r.headers["location"] == "/kupony"
    assert started == [True]


def test_ranking_follows_chart_range_and_shows_year_for_old_purchases(client: TestClient) -> None:
    history = client.app.state.history  # type: ignore[attr-defined]
    old = (date.today() - timedelta(days=500)).isoformat()
    recent = (date.today() - timedelta(days=10)).isoformat()
    history.upsert_tickets(
        "osoba-1",
        [{"id": "o", "date": f"{old}T10:00:00+00:00"}, {"id": "n", "date": f"{recent}T10:00:00+00:00"}],
    )
    history.save_detail("o", "S", ParsedReceipt(items=[ReceiptItem("n:1", "Produkt stary", 1, 2.0, 2.0)]))
    history.save_detail("n", "S", ParsedReceipt(items=[ReceiptItem("2", "Produkt nowy", 1, 3.0, 3.0)]))
    default = client.get("/produkty").text
    ranking = default[default.index('id="rank"') :]
    assert "Produkt nowy" in ranking and "Produkt stary" not in ranking
    everything = client.get("/produkty?zakres=all").text
    ranking = everything[everything.index('id="rank"') :]
    assert "Produkt stary" in ranking and f" {date.fromisoformat(old).year}" in ranking
    assert "zakres=all" in ranking[ranking.index("Produkt stary") :].split("Wykres")[0]


def test_product_search_filters_ranking_and_offers_clear(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?q=produkt a").text
    ranking = text[text.index('id="rank"') :]
    assert "Produkt A" in ranking and "Produkt B" not in ranking
    assert "1 z 2" in ranking and "wyczyść" in ranking
    assert (
        'type="search"' in text and 'name="q"' in text and 'name="produkt"' not in text.split('id="rank"')[0]
    )


def test_search_ignores_case_and_polish_diacritics(client: TestClient) -> None:
    from lidl.text import matches

    assert matches("Jabłka Pinova luz", "JABLKA") and matches("Pieczarki 500g", "piecz")
    assert not matches("Banany luz", "jablka")


def test_selected_product_shows_as_removable_chip(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?produkt=111").text
    assert "Produkt: <strong>Produkt A</strong>" in text and "Usuń filtr produktu" in text
    assert "<select" not in text and "htmx.min.js?v=" in text


def test_live_search_returns_only_the_ranking_results(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?q=produkt b", headers={"HX-Target": "wyniki"}).text
    assert text.lstrip().startswith('<div id="wyniki"') and "Produkt B" in text and "Produkt A" not in text
    assert "Wydatki w czasie" not in text and "<html" not in text


def test_search_matches_every_word_in_any_order() -> None:
    from lidl.text import matches

    assert matches("Ser gouda plastry 150 g", "plastry ser") and not matches("Ser gouda", "ser mleko")


def test_coupons_search_filters_only_regular_products_and_live_returns_the_list_only(
    client: TestClient,
) -> None:
    _seed_regular(client)
    _seed_coupons(client)
    text = client.get("/kupony?q=produkt a").text
    regular = text.split('id="cp-h"')[1]
    assert "Produkt A" in regular and "Produkt C" not in regular and "1 z 2" in regular
    assert (
        "Kupon aktywny" in text and "Kupon do aktywacji" in text and "pasuje" not in text
    )  # kupony kont bez filtra
    part = client.get("/kupony?q=produkt a", headers={"HX-Target": "kupony-wyniki"}).text
    assert part.lstrip().startswith('<div id="kupony-wyniki"') and "<html" not in part
    assert "Produkt A" in part and "Produkt C" not in part
    for other in ("kupony-konta", "Nagrody", "Efekt kuponów", "Kupowane regularnie", 'id="q"'):
        assert other not in part


def test_coupons_sections_are_ordered_and_search_sits_in_regular_products(client: TestClient) -> None:
    now = datetime.now(UTC)
    _seed_effect(client, now)
    _seed_regular(client)
    text = client.get("/kupony").text
    order = [text.index(h) for h in ("Kupony w tym tygodniu", "Nagrody", "Efekt kuponów", 'id="cp-h"')]
    assert order == sorted(order)
    assert text.index('id="cp-h"') < text.index('id="q"') < text.index('id="kupony-wyniki"')
    assert text.count('id="q"') == 1


def test_coupons_controls_update_in_place(client: TestClient, monkeypatch) -> None:
    _seed_regular(client)
    _seed_coupons(client)
    text = client.get("/kupony").text
    assert 'hx-post="/kupony/produkt/111"' in text and 'hx-select="#p-111"' in text
    assert 'hx-post="/kupony/osoba-1/b/aktywuj"' in text and 'hx-post="/kupony/sprawdz"' in text
    assert 'hx-trigger="every 3s"' not in text and 'http-equiv="refresh"' not in text
    monkeypatch.setattr(client.app.state.job, "running", True)  # type: ignore[attr-defined]
    assert 'hx-trigger="every 3s"' in client.get("/kupony").text


def test_check_now_keeps_the_search_phrase(client: TestClient, monkeypatch) -> None:
    job = client.app.state.job  # type: ignore[attr-defined]
    monkeypatch.setattr(job, "start_coupons", lambda: True)
    r = client.post("/kupony/sprawdz", data={"q": "ser plastry"})
    assert r.status_code == 303 and r.headers["location"] == "/kupony?q=ser+plastry"


def test_polling_during_check_returns_only_account_cards(client: TestClient) -> None:
    _seed_regular(client)
    _seed_coupons(client)
    part = client.get("/kupony", headers={"HX-Target": "kupony-konta"}).text
    assert part.lstrip().startswith('<div id="kupony-konta"') and "Kupon aktywny" in part
    assert "Kupowane regularnie" not in part and "<html" not in part


def test_search_covers_products_beyond_the_first_two_hundred(client: TestClient) -> None:
    history = client.app.state.history  # type: ignore[attr-defined]
    day = (date.today() - timedelta(days=3)).isoformat()
    history.upsert_tickets("osoba-1", [{"id": "duzy", "date": f"{day}T10:00:00+00:00"}])
    items = [ReceiptItem(str(1000 + i), f"Produkt {i:03d}", 1, 1.0, 1.0) for i in range(204)]
    items.append(ReceiptItem("9999", "Zzz rzadki produkt", 1, 1.0, 1.0))
    history.save_detail("duzy", "S", ParsedReceipt(items=items))
    part = client.get("/produkty?q=rzadki", headers={"HX-Target": "wyniki"}).text
    assert "Zzz rzadki produkt" in part and "1 z 205" in part


def _seed_second_account(client: TestClient) -> None:
    """Osoba 2 ma wspólny „Kupon aktywny” i własny „Kupon drugiej osoby”."""
    from datetime import UTC, datetime

    from lidl.coupons import parse_coupons

    _connect(client, "Osoba 2")
    now = datetime.now(UTC)
    validity = {"start": (now - timedelta(days=1)).isoformat(), "end": (now + timedelta(days=3)).isoformat()}
    promos = [
        {"id": pid, "promotionId": pid, "title": title, "discount": {"title": "-30%"}, "validity": validity,
         "isActivated": False, "articleIds": []}
        for pid, title in (("a2", "Kupon aktywny"), ("x2", "Kupon drugiej osoby"))
    ]  # fmt: skip
    history = client.app.state.history  # type: ignore[attr-defined]
    history.save_coupons(
        "osoba-2", parse_coupons({"sections": [{"name": "AllStores", "promotions": promos}]}), now.isoformat()
    )


def test_account_coupons_are_collapsed_tabs_with_shared_and_unique_tags(client: TestClient) -> None:
    _seed_coupons(client)
    _seed_second_account(client)
    text = client.get("/kupony").text
    assert text.count("data-tab aria-controls") == 2 and 'aria-expanded="true"' not in text
    assert 'id="kupony-osoba-1" role="region"' in text and text.count("hidden>") >= 2
    assert "tylko tu: 2" in text and "tylko tu: 1" in text
    one = text[text.index('id="kupony-osoba-1"') : text.index('id="kupony-osoba-2"')]
    assert (
        "wspólny" in one.split("Kupon do aktywacji")[0]
        and "tylko Osoba 1" in one.split("Kupon do aktywacji")[1]
    )
    two = text[text.index('id="kupony-osoba-2"') :]
    assert "tylko Osoba 2" in two.split("Kupon drugiej osoby")[1]


def test_search_does_not_open_or_filter_account_tabs(client: TestClient) -> None:
    _seed_coupons(client)
    _seed_second_account(client)
    text = client.get("/kupony?q=drugiej").text
    assert (
        'aria-expanded="true"' not in text and "Kupon drugiej osoby" in text and "Kupon do aktywacji" in text
    )


def test_single_account_has_no_shared_tags(client: TestClient) -> None:
    _seed_coupons(client)
    text = client.get("/kupony").text
    assert "wspólny" not in text and "tylko Osoba 1" not in text


def test_coupons_page_shows_rewards_per_account(client: TestClient) -> None:
    _connect(client)
    _connect(client, "Osoba 2")
    today = date.today()
    card = ScratchCard(
        "Scratch",
        datetime.combine(today - timedelta(days=3), time(19)).astimezone(),
        datetime.combine(today, time(23, 59, 59)).astimezone(),
    )
    goals = (
        Goal(50, True, "Kupon A", "-10 zł"),
        Goal(300, True, "Produkt B", "-20%"),
        Goal(500, False, "Produkt C LUB Produkt D", "-50%"),
        Goal(1500, False, "Produkt E", "-30%"),
    )
    client.app.state.rewards.last = {  # type: ignore[attr-defined]
        "Osoba 1": Rewards((card,), CouponPlus(335.7, goals, today + timedelta(days=23))),
        "Osoba 2": Rewards((), None),
    }
    text = client.get("/kupony").text
    assert "Nagrody" in text and "Kończy się dziś o 23:59" in text
    assert "Brakuje <strong>164,30\u00a0zł</strong> do progu 500\u00a0zł" in text
    assert "Produkt C LUB Produkt D" in text and "-50%" in text and "24 dni do końca" in text
    assert 'style="--p: 22.38%"' in text and 'style="--g: 33.33%"' in text
    assert "Brak zdrapek i akcji Kupon Plus." in text


def test_reward_goal_labels_skip_crowded_thresholds() -> None:
    # progi 50/300/500 na początku akcji leżą blisko siebie — podpis 500 nachodziłby na 300
    goals = tuple(Goal(v, False, "Produkt A", "10 zł rabatu*") for v in (50, 300, 500, 1000, 1500))
    today = date.today()
    [card] = reward_cards({"Osoba 1": Rewards((), CouponPlus(40.32, goals, today))}, today)
    assert card["label"] == "Osoba 1"
    assert [g["label"] for g in card["plus"]["goals"]] == [True, False, True, True, True]
    assert card["plus"]["next"]["discount"] == "10 zł rabatu"


def test_coupons_page_rewards_pending_before_first_read(client: TestClient) -> None:
    _connect(client)
    assert "pojawią się po pierwszym sprawdzeniu" in client.get("/kupony").text


def _effect_payload(now: datetime, *promos: tuple[str, list[str], int]) -> dict[str, object]:
    """Kupony aktywowane, ważne od `now - 8 dni` do `now + dni` (trzecia wartość krotki)."""
    return {
        "sections": [
            {
                "name": "AllStores",
                "promotions": [
                    {
                        "id": pid, "promotionId": pid, "title": f"Kupon {pid}", "discount": {"title": "-30%"},
                        "validity": {
                            "start": (now - timedelta(days=8)).isoformat(),
                            "end": (now + timedelta(days=days)).isoformat(),
                        },
                        "isActivated": True, "articleIds": codes,
                    }
                    for pid, codes, days in promos
                ],
            }
        ]
    }  # fmt: skip


def _seed_effect(client: TestClient, now: datetime) -> list:
    """Dwa konta niepotrzebne: jedno konto, paragon z kuponem na 111 w oknie ważności kuponów."""
    from lidl.coupons import parse_coupons

    _connect(client)
    history = client.app.state.history  # type: ignore[attr-defined]
    day = (now - timedelta(days=2)).astimezone().date()
    history.upsert_tickets("osoba-1", [{"id": "t1", "date": f"{day.isoformat()}T10:00:00+00:00"}])
    history.save_detail(
        "t1",
        "S",
        ParsedReceipt(items=[ReceiptItem("111", "Produkt", 1, 10, 10, discount=-35.0, coupon=-30.0)]),
    )
    payload = _effect_payload(
        now, ("used", ["111", "999"], -1), ("lost", ["222"], -1), ("wait", ["222"], 3), ("none", [], -1)
    )
    history.save_coupons("osoba-1", parse_coupons(payload), now.isoformat())
    return client.app.state.service.store.list()  # type: ignore[attr-defined]


def test_effect_view_numbers_and_coupon_outcomes(client: TestClient) -> None:
    now = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)  # okno 30 dni nie nachodzi na okres sprzed add-onu
    accounts = _seed_effect(client, now)
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets("osoba-1", [{"id": "base", "date": "2026-06-01T10:00:00+00:00"}])
    history.save_detail(
        "base",
        "S",
        ParsedReceipt(items=[ReceiptItem("5", "Stary", 1, 10, 10, discount=-109.5, coupon=-73.0)]),
    )
    v = effect_view(history, accounts, now.date(), now)
    assert (v["now"], v["before"]) == ("30,00 zł", "6,00 zł")
    assert (v["now_pct"], v["before_pct"]) == (100, 20)
    assert v["delta"] == {"kind": "up", "text": "O 24,00 zł (400%) więcej niż zwykle"}
    assert v["promotions"] == "5,00 zł" and v["promotions_before"] == "3,00 zł"
    assert v["summary"] == "Wykorzystane 1 z 2 zakończonych (50%)"
    assert {r["title"]: (r["kind"], r["status"]) for r in v["rows"]} == {
        "Kupon used": ("on", "Wykorzystany"),
        "Kupon lost": ("err", "Przepadł"),
        "Kupon wait": ("wait", "W toku"),
        "Kupon none": ("none", "Brak danych"),
    }
    assert {r["who"] for r in v["rows"]} == {"Osoba 1"}


def test_effect_view_hides_comparison_until_window_is_after_addon_start(client: TestClient) -> None:
    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)  # okno 30 dni wciąż zawiera 6.10
    accounts = _seed_effect(client, now)
    history = client.app.state.history  # type: ignore[attr-defined]
    v = effect_view(history, accounts, now.date(), now)
    assert v["ready"] is False
    assert v["not_ready"] == "Porównanie od 6 lis — wtedy 30 dni będzie w całości z add-onem"
    assert effect_view(history, accounts, date(2026, 11, 6), now)["ready"] is True  # type: ignore[index]
    from jinja2 import Environment, FileSystemLoader

    from lidl.web.app import HERE

    html = (
        Environment(loader=FileSystemLoader(HERE / "templates")).get_template("_effect.html").render(effect=v)
    )
    assert "Średnio przed add-onem" not in html and "Porównanie od 6 lis" in html


def test_effect_view_without_data_is_hidden(client: TestClient) -> None:
    _connect(client)
    now = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
    accounts = client.app.state.service.store.list()  # type: ignore[attr-defined]
    assert effect_view(client.app.state.history, accounts, now.date(), now) is None  # type: ignore[attr-defined]


def test_effect_view_without_activated_coupons_says_we_collect_data(client: TestClient) -> None:
    now = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
    _connect(client)
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets("osoba-1", [{"id": "t", "date": "2026-11-28T10:00:00+00:00"}])
    history.save_detail(
        "t", "S", ParsedReceipt(items=[ReceiptItem("1", "P", 1, 10, 10, discount=-2.0, coupon=-2.0)])
    )
    accounts = client.app.state.service.store.list()  # type: ignore[attr-defined]
    v = effect_view(history, accounts, now.date(), now)
    assert v is not None and v["rows"] == [] and v["summary"] == "Jeszcze nic do podsumowania"
    assert v["delta"]["text"] == "Brak paragonów sprzed add-onu do porównania"


def test_effect_view_lists_only_the_last_30_days_of_coupons(client: TestClient) -> None:
    from lidl.coupons import parse_coupons

    now = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
    _connect(client)
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets("osoba-1", [{"id": "t", "date": "2026-11-28T10:00:00+00:00"}])
    history.save_detail(
        "t", "S", ParsedReceipt(items=[ReceiptItem("1", "P", 1, 10, 10, discount=-2.0, coupon=-2.0)])
    )
    history.save_coupons("osoba-1", parse_coupons(_effect_payload(now, ("old", ["1"], -40))), now.isoformat())
    accounts = client.app.state.service.store.list()  # type: ignore[attr-defined]
    assert effect_view(history, accounts, now.date(), now)["rows"] == []  # type: ignore[index]


def test_coupons_page_shows_the_effect_section(client: TestClient) -> None:
    _seed_effect(client, datetime.now(UTC))
    text = client.get("/kupony").text
    assert 'id="efekt-h"' in text and "Efekt kuponów" in text
    for word in ("Wykorzystany", "Przepadł", "W toku", "Brak danych", "Wykorzystane 1 z 2 zakończonych"):
        assert word in text
    for target in ("kupony-konta", "kupony-wyniki"):  # odświeżanie i wyszukiwanie jej nie dotykają
        assert "Efekt kuponów" not in client.get("/kupony", headers={"hx-target": target}).text


def test_coupons_page_without_any_data_has_no_effect_section(client: TestClient) -> None:
    _connect(client)
    assert "Efekt kuponów" not in client.get("/kupony").text


def test_search_offers_rare_products_and_star_moves_them_onto_the_list(client: TestClient) -> None:
    _seed_regular(client)
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets("osoba-1", [{"id": "rare", "date": "2026-08-01T10:00:00+00:00"}])
    history.save_detail(
        "rare", "S", ParsedReceipt(items=[ReceiptItem("333", "Filet z indyka XXL", 1, 30, 30)])
    )
    assert "Inne kupowane produkty" not in client.get("/kupony").text  # tylko przy wyszukiwaniu
    text = client.get("/kupony", params={"q": "indyk"}).text
    assert "Inne kupowane produkty" in text and 'aria-label="Obserwuj: Filet z indyka XXL"' in text
    client.post("/kupony/produkt/333/obserwuj", data={"on": "1"})
    text = client.get("/kupony").text
    assert "spoza listy" in text and "Inne kupowane produkty" not in text
    assert 'aria-label="Auto-aktywacja kuponów: Filet z indyka XXL"' not in text  # bez przełącznika
    assert "<dt>Produkty</dt><dd>2</dd>" in text and "<dt>Obserwowane</dt><dd>1</dd>" in text
    client.post("/kupony/produkt/333/obserwuj", data={"on": "0"})
    assert "Filet z indyka XXL" not in client.get("/kupony").text


# --- Ceny (E7) -----------------------------------------------------------------


def _seed_prices(client: TestClient) -> None:
    """Rok temu i miesiąc temu: Masło +10%, Cukier −10%; Banany (ważone) tylko teraz."""
    history = client.app.state.history  # type: ignore[attr-defined]
    today = date.today()
    old, new = today - timedelta(days=395), today - timedelta(days=30)
    history.upsert_tickets(
        "osoba-1", [{"id": t, "date": f"{d}T10:00:00+00:00"} for t, d in (("old", old), ("new", new))]
    )
    history.save_detail(
        "old",
        "S",
        ParsedReceipt(
            items=[ReceiptItem("111", "Masło", 1, 6.0, 6.0), ReceiptItem("222", "Cukier", 1, 4.0, 4.0)]
        ),
    )
    history.save_detail(
        "new",
        "S",
        ParsedReceipt(
            items=[
                ReceiptItem("111", "Masło", 1, 6.6, 6.6),
                ReceiptItem("222", "Cukier", 1, 3.6, 3.6),
                ReceiptItem("333", "Banany", 2.0, 5.0, 10.0, is_weight=True),
            ]
        ),
    )


def test_top_changes_skip_products_with_small_spend() -> None:
    small = PriceChange("1", "Brzoskwinie", True, 7.99, 14.99, 87.6, 3.0)
    big = PriceChange("2", "Masło", False, 6.0, 6.6, 10.0, 60.0)
    cheaper = PriceChange("3", "Arbuz", True, 7.99, 3.49, -56.3, 49.99)
    assert top_changes([small, big, cheaper]) == ([big], [])


def test_prices_shows_basket_top_changes_and_list(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prices, "TOP_MIN_SPEND", 0)  # dane testowe mają wydatki po kilka zł
    _seed_prices(client)
    text = client.get("/ceny").text
    assert 'aria-current="page">Ceny<' in text
    assert "Nasz koszyk" in text and "+2,9%" in text
    assert "Porównanie dla <strong>2 produktów</strong>" in text and "<strong>50%</strong>" in text
    assert "Co nie jest porównane" in text and "Pierwszy zakup w ostatnim roku" in text
    assert "10,00 zł · 1 produkt · 50%" in text
    assert "co najmniej 50 zł rocznie" in text
    up, down = text.index("Najbardziej podrożały"), text.index("Najbardziej potaniały")
    assert up < text.index("Masło", up) < down < text.index("Cukier", down)
    assert "6,00 zł → 6,60 zł" in text and "+10,0%" in text and "−10,0%" in text
    assert 'href="/ceny/produkt/111"' in text and "7 zł rocznie" in text
    assert "Pierwszy zakup w ostatnim roku, np.: Banany." in text
    assert "Banany" not in text[text.index('id="ceny-wyniki"') :]  # bez zakupu rok temu nie ma porównania


def test_prices_live_search_and_order_return_only_the_list(client: TestClient) -> None:
    _seed_prices(client)
    r = client.get("/ceny?q=cukier", headers={"hx-target": "ceny-wyniki"})
    assert r.text.lstrip().startswith('<div id="ceny-wyniki"')
    assert "Cukier" in r.text and "Masło" not in r.text and "1 z 2" in r.text
    by_spend = client.get("/ceny?kolejnosc=wydatki", headers={"hx-target": "ceny-wyniki"}).text
    assert by_spend.index("Masło") < by_spend.index("Cukier")
    by_change = client.get("/ceny?kolejnosc=zmiana", headers={"hx-target": "ceny-wyniki"}).text
    assert by_change.index("Masło") < by_change.index("Cukier")
    assert "Nic nie pasuje do „kawa”" in client.get("/ceny?q=kawa").text


def test_prices_without_history_or_comparison_say_why(client: TestClient) -> None:
    assert "Brak historii zakupów" in client.get("/ceny").text
    _seed(client, (date.today().isoformat(),))
    text = client.get("/ceny").text
    assert "Za krótka historia" in text and "Nasz koszyk" not in text


def test_product_prices_page_shows_facts_chart_and_link_to_spending(client: TestClient) -> None:
    _seed_prices(client)
    r = client.get("/ceny/produkt/111", headers={"x-ingress-path": "/api/hassio_ingress/abc"})
    assert r.status_code == 200
    text = r.text
    assert '<h1 class="t">Masło</h1>' in text and "Cena za sztukę · 2 zakupy" in text
    assert "Rok temu" in text and "6,00 zł" in text and "+10,0%" in text
    assert 'class="ln__line"' in text and text.count('class="ln__dot"') == 2
    assert 'href="/api/hassio_ingress/abc/produkty?produkt=111&amp;zakres=all#wykres"' in text
    bananas = client.get("/ceny/produkt/333").text
    assert "Cena za kg" in bananas and "5,00 zł/kg" in bananas and "Brak porównania rok do roku" in bananas


def test_unknown_product_prices_page_is_404(client: TestClient) -> None:
    r = client.get("/ceny/produkt/999")
    assert r.status_code == 404 and "Nie ma takiego produktu" in r.text


def test_prices_split_shows_old_receipt_codes_and_examples(client: TestClient) -> None:
    _seed_prices(client)
    history = client.app.state.history  # type: ignore[attr-defined]
    day = date.today() - timedelta(days=200)
    history.upsert_tickets("osoba-1", [{"id": "nat", "date": f"{day}T10:00:00+00:00"}])
    history.save_detail("nat", "S", ParsedReceipt(items=[ReceiptItem("n:5901", "Ser zolty", 1, 9.0, 9.0)]))
    text = client.get("/ceny").text
    assert "w tym ze starych paragonów: 9,00 zł · 1 produkt" in text
    assert "Ze starych paragonów, niekupowane od 6 miesięcy, np.: Ser zolty." in text


def test_merge_candidates_export_is_json_without_cache(client: TestClient) -> None:
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets("osoba-1", [{"id": "o", "date": "2026-01-10T10:00:00+00:00"}])
    history.save_detail("o", "S", ParsedReceipt(items=[ReceiptItem("n:9", "Ser zolty", 1, 9.0, 9.0)]))
    r = client.get("/produkty/laczenie/kandydaci.json")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["old"][0]["code"] == "n:9" and r.json()["new"] == []


def test_merge_import_replaces_pairs_and_empty_list_undoes(client: TestClient) -> None:
    r = client.post("/produkty/laczenie/import", json=[{"old": "n:9", "new": "0000009"}])
    assert r.status_code == 200 and r.json() == {"merges": 1}
    assert client.post("/produkty/laczenie/import", json=[]).json() == {"merges": 0}


def _seed_receipts(client: TestClient) -> None:
    """Paragon HTML z kuponem i kaucją, starszy NATIVE pod starą nazwą (`merges`), paragon bez pozycji."""
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets(
        "osoba-1",
        [
            {"id": "t-new", "date": "2026-10-05T10:00:00+00:00", "totalAmount": 13.0, "storeCode": "PL0002"},
            {"id": "t-old", "date": "2025-03-02T10:00:00+00:00", "totalAmount": 12.0, "storeCode": "PL0001"},
            {"id": "t-wait", "date": "2026-10-06T10:00:00+00:00", "totalAmount": 7.0, "storeCode": "PL0002"},
        ],
    )
    store = {"code": "PL0002", "name": "Miasto A Ulica B", "address": "", "postal": "", "locality": ""}
    history.save_detail(
        "t-new",
        None,
        ParsedReceipt(
            items=[
                ReceiptItem("555", "Filet z indyka XXL", 1, 11.0, 11.0, discount=-2.5, coupon=-2.0,
                            promo="Lidl Plus kupon; Rabat grupowy"),
                ReceiptItem("111", "Mleko UHT", 2, 2.0, 4.0),
            ],
            purchased_at="2026-10-05T19:39:20",
            store=store,
            payment="Karta",
            deposit_charged=0.5,
        ),
    )  # fmt: skip
    history.save_detail(
        "t-old", None, ParsedReceipt(items=[ReceiptItem("n:5", "Fil.z ind.XXL", 1, 12.0, 12.0)])
    )
    history.set_merges([("n:5", "555")])


def test_receipts_tab_lists_months_with_totals_and_statuses(client: TestClient) -> None:
    _seed_receipts(client)
    r = client.get("/paragony")
    assert r.status_code == 200 and 'aria-current="page">Paragony' in r.text
    assert "Październik 2026" in r.text and "2 paragony · 20,00 zł" in r.text
    assert "Marzec 2025" in r.text
    assert "pon 5 paź, 19:39" in r.text
    assert "Miasto A Ulica B" in r.text and "taniej o 2,50 zł" in r.text and "Bez pozycji" in r.text


def test_receipts_filters_and_live_list(client: TestClient) -> None:
    _seed_receipts(client)
    r = client.get("/paragony?sklep=PL0001", headers={"hx-target": "paragony-lista"})
    assert 'id="paragony-lista"' in r.text and "<h1" not in r.text
    assert "Marzec 2025" in r.text and "Październik 2026" not in r.text
    bad = client.get("/paragony?od=2026-10-10&do=2026-10-01")
    assert "późniejsza" in bad.text and "Październik 2026" not in bad.text
    none = client.get("/paragony?od=2027-01-01")
    assert "Żaden paragon nie pasuje" in none.text


def test_receipts_more_link_after_limit(client: TestClient) -> None:
    _seed_receipts(client)
    r = client.get("/paragony?limit=1")
    assert "Pokaż więcej" in r.text and "limit=31" in r.text
    assert "Marzec 2025" not in r.text


def test_receipts_search_finds_old_names_and_links_purchases(client: TestClient) -> None:
    _seed_receipts(client)
    r = client.get("/paragony?q=fil.z", headers={"hx-target": "paragony-produkty"})
    assert 'id="paragony-produkty"' in r.text and "<h1" not in r.text
    assert "Filet z indyka XXL" in r.text and "2 zakupy" in r.text
    assert "/paragony/produkt/555?q=fil.z" in r.text
    assert "Nic nie pasuje" in client.get("/paragony?q=chleb").text


def test_receipt_detail_shows_lines_discounts_and_bill(client: TestClient) -> None:
    _seed_receipts(client)
    r = client.get("/paragony/t-new?produkt=555")
    assert r.status_code == 200
    assert "pon 5 paź 2026, 19:39" in r.text and "Karta" in r.text
    assert 'class="rl rl--hit" id="szukany"' in r.text and "Szukany produkt" in r.text
    assert "Kupon Lidl Plus" in r.text and "Rabat grupowy" in r.text and "−0,50 zł" in r.text
    assert "2 pozycje · szukany produkt" in r.text and "built-in" not in r.text
    assert "2 × 2,00 zł" in r.text and "Kaucje pobrane" in r.text and "+0,50 zł" in r.text
    assert "/paragony/produkt/555" in r.text  # powrót do zakupów produktu
    assert "nie są jeszcze pobrane" in client.get("/paragony/t-wait").text
    assert client.get("/paragony/brak").status_code == 404


def test_product_purchases_page_summary_and_rows(client: TestClient) -> None:
    _seed_receipts(client)
    r = client.get("/paragony/produkt/555?q=indyk")
    assert r.status_code == 200
    assert "Kupiony na 2 paragonach, ostatnio 5 paź 2026" in r.text and "Fil.z ind.XXL" in r.text
    assert "2 szt." in r.text and "20,50 zł" in r.text and "11,00–12,00 zł" in r.text
    assert "/paragony/t-new?produkt=555#szukany" in r.text and "/ceny/produkt/555" in r.text
    assert "/paragony?q=indyk" in r.text
    assert client.get("/paragony/produkt/999").status_code == 404


def test_receipts_without_history_say_where_to_import(client: TestClient) -> None:
    assert "Pobierz ją w zakładce Produkty" in client.get("/paragony").text


def test_products_ranking_and_prices_link_to_product_purchases(client: TestClient) -> None:
    _seed_receipts(client)
    assert 'class="rk__name" href="/paragony/produkt/555"' in client.get("/produkty?zakres=all").text
    assert 'href="/paragony/produkt/555">Zakupy tego produktu' in client.get("/ceny/produkt/555").text
