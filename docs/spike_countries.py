"""Spike: czy konto Lidl Plus widzi paragony z innych krajów. Tylko odczyt.

Użycie (z katalogu app), dwa kroki (bez stdin — działa z `!`):
  1) uv run python <ten plik> PL            -> wypisuje adres, zapisuje verifier PKCE (plik 600)
  2) uv run python <ten plik> PL '<Location lub kod>'  -> wymienia kod i sprawdza kraje
Tokeny zostają w pamięci; wypisuje tylko liczby, daty, sumy i nazwy kluczy.
"""
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")

from lidl.client.api import LidlPlusApi  # noqa: E402
from lidl.client.auth import OAuthLogin, auth_code_from_redirect  # noqa: E402
from lidl.client.exceptions import LidlPlusError  # noqa: E402

LANG = {"PL": "pl-PL", "CZ": "cs-CZ", "IT": "it-IT"}
VERIFIER = Path.home() / ".cache" / "lidl_spike_verifier"
KEEP = re.compile(r"date|total|currency|amount", re.I)


def brief(t: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in t.items() if KEEP.search(k) and not isinstance(v, (dict, list)))


async def main() -> None:
    login_country = (sys.argv[1] if len(sys.argv) > 1 else "PL").upper()
    login = OAuthLogin.create(country=login_country, language=LANG[login_country])
    try:
        if len(sys.argv) < 3:
            url = login.prepare()
            VERIFIER.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(VERIFIER, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(login.verifier)
            print(f"\nOtwórz w przeglądarce i zaloguj się (kraj logowania: {login_country}):\n{url}\n")
            return
        verifier = VERIFIER.read_text().strip()
        tokens = await login.exchange_code(auth_code_from_redirect(sys.argv[2]), verifier)
        VERIFIER.unlink()
        for country in ("PL", "CZ", "IT"):
            api = LidlPlusApi(
                login._session, tokens["access_token"], tokens["refresh_token"],
                country=country, language=LANG[country],
            )
            for offset in (0, 1):
                try:
                    items = await api.tickets(offset)
                except LidlPlusError as err:
                    print(f"{country} yearOffset={offset}: BŁĄD {type(err).__name__}: {err}")
                    continue
                print(f"{country} yearOffset={offset}: {len(items)} paragonów")
                if items and offset == 0:
                    print("  klucze listy:", sorted(items[0].keys()))
                for t in items[:5]:
                    print("  ", brief(t))
                if items and country != "PL" and offset == 0:
                    try:
                        d = await api.ticket(str(items[0]["id"]))
                        print("  klucze detalu:", sorted(d.keys()))
                        print("  waluta/suma detalu:", brief(d))
                    except LidlPlusError as err:
                        print(f"  detal: BŁĄD {type(err).__name__}: {err}")
            tokens = {"access_token": api.access_token, "refresh_token": api.refresh_token}
    finally:
        await login.close()


asyncio.run(main())
