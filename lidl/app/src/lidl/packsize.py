"""Odczyt gramatury z nazwy produktu (czysta funkcja, bez I/O)."""

import re

_PACK_RE = re.compile(
    r"(?<!\d)(?<!\d[.,])"
    r"(?:(?P<mult>\d+)\s*[x×]\s*)?"
    r"(?P<num>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>kg|g|ml|cl|l|szt(?:uk)?)"
    r"(?![^\W\d_])",
    re.IGNORECASE,
)

# jednostka -> (jednostka bazowa, mnożnik)
_UNITS: dict[str, tuple[str, float]] = {
    "g": ("kg", 0.001),
    "kg": ("kg", 1.0),
    "ml": ("l", 0.001),
    "cl": ("l", 0.01),
    "l": ("l", 1.0),
    "szt": ("szt", 1.0),
    "sztuk": ("szt", 1.0),
}


def pack_size(name: str) -> tuple[float, str] | None:
    """Zwraca (ilość, 'kg'|'l'|'szt') z nazwy albo None, gdy brak gramatury."""
    m = _PACK_RE.search(name)
    if m is None:
        return None
    base, factor = _UNITS[m.group("unit").lower()]
    qty = float(m.group("num").replace(",", ".")) * factor
    if m.group("mult"):
        qty *= int(m.group("mult"))
    if qty <= 0:
        return None
    return round(qty, 6), base


def base_name(name: str) -> str:
    """Nazwa bez gramatury: małe litery, zwinięte spacje, bez końcowych kropek/myślników."""
    stripped = re.sub(r"\s+", " ", _PACK_RE.sub(" ", name, count=1).lower())
    return stripped.strip(" .-–")
