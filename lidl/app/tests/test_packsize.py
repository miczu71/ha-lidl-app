"""Odczyt gramatury z nazwy produktu (neutralne nazwy)."""

import pytest

from lidl.packsize import base_name, pack_size


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Produkt A 500g", (0.5, "kg")),
        ("Produkt A 500 g", (0.5, "kg")),
        ("Produkt A 1kg", (1.0, "kg")),
        ("Produkt A 1,5 kg", (1.5, "kg")),
        ("Napój B 1,5l", (1.5, "l")),
        ("Napój B 0.75 l", (0.75, "l")),
        ("Napój B 330ml", (0.33, "l")),
        ("Napój B 50cl", (0.5, "l")),
        ("Produkt A 2x500g", (1.0, "kg")),
        ("Napój B 6x1,5l", (9.0, "l")),
        ("Napój B 6 x 330ml", (1.98, "l")),
        ("PRODUKT A 500G", (0.5, "kg")),
        ("Napój B 1L", (1.0, "l")),
        ("Produkt A 500g bio", (0.5, "kg")),
        ("Produkt A 500g Premium extra", (0.5, "kg")),
        ("Winog.jas.bezp.500g", (0.5, "kg")),
        ("Produkt C 10 szt", (10.0, "szt")),
        ("Produkt C 10szt.", (10.0, "szt")),
        ("Produkt C 3x10 szt", (30.0, "szt")),
    ],
)
def test_pack_size(name: str, expected: tuple[float, str]) -> None:
    result = pack_size(name)
    assert result is not None
    assert result[1] == expected[1]
    assert result[0] == pytest.approx(expected[0])


@pytest.mark.parametrize(
    "name",
    ["Produkt A", "Skyr 2", "Tort 1", "Produkt A 2 smaki", "Produkt 500 gramofon", "", "Produkt A 3x"],
)
def test_pack_size_none(name: str) -> None:
    assert pack_size(name) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Produkt A 500g", "produkt a"),
        ("Produkt A 2x500g", "produkt a"),
        ("Napój B 6 x 1,5l", "napój b"),
        ("Winog.jas.bezp.500g", "winog.jas.bezp"),
        ("Produkt A 500g bio", "produkt a bio"),
        ("  Produkt   A  - 1kg ", "produkt a"),
        ("Skyr 2", "skyr 2"),
    ],
)
def test_base_name(name: str, expected: str) -> None:
    assert base_name(name) == expected


def test_base_name_same_for_different_pack() -> None:
    assert base_name("Produkt A 500g") == base_name("Produkt A 450 g")


@pytest.mark.parametrize("name", ["Cola 0l", "Woda 0g", "Produkt 0,0l"])
def test_pack_size_zero_is_none(name: str) -> None:
    assert pack_size(name) is None
