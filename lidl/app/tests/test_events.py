from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from lidl.history import History
from lidl.promotions import Promotion

T0 = datetime(2026, 10, 12, 7, 0)


def test_events_newest_first_and_filtered_by_area(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.log_event("daily", "ok", "Poranny przebieg", {"tickets": 2}, duration_ms=48000, at=T0)
    h.log_event("ai", "warn", "Model odmówił", {"model": "m1", "http": 429}, at=T0.replace(minute=5))
    events = h.events(T0.replace(hour=0))
    assert [e.summary for e in events] == ["Model odmówił", "Poranny przebieg"]
    assert events[1].detail == {"tickets": 2} and events[1].duration_ms == 48000
    assert [e.area for e in h.events(T0.replace(hour=0), area="daily")] == ["daily"]


def test_prune_drops_events_older_than_cutoff(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.log_event("daily", "ok", "stary", at=T0.replace(month=9))
    h.log_event("daily", "ok", "nowy", at=T0)
    h.prune_events(T0.replace(day=1))
    assert [e.summary for e in h.events(T0.replace(year=2025))] == ["nowy"]


def test_leaflet_progress_counts_batches_per_flyer(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    start, end = date.today(), date.today() + timedelta(days=2)
    h.add_leaflet("f1", [[[1, "u"]], [[2, "u"]], [[3, "u"]]], start, end)
    h.set_leaflet_batch("f1", 0, "done", 1, "")
    h.set_leaflet_batch("f1", 1, "failed", 30, "2026-10-12T12:40:00")
    h.set_leaflet_batch("f1", 2, "pending", 2, "2026-10-12T12:50:00")
    h.save_leaflet_matches("f1", [Promotion("0000111", "Produkt A", "-30%", start, end)])
    (p,) = h.leaflet_progress()
    assert (p.flyer_id, p.start, p.end) == ("f1", start, end)
    assert (p.done, p.pending, p.failed, p.matches) == (1, 1, 1, 1)
    assert p.next_try == datetime(2026, 10, 12, 12, 50)
