"""Wspólny parser dat ISO."""

from __future__ import annotations

from datetime import date


def parse_date(value: str | None) -> date | None:
    """Data ISO (także z czasem, np. ``2026-11-21T22:59:59Z``); pusta albo nieczytelna → None."""
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None
