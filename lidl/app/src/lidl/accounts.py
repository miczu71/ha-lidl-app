"""Konta Lidl Plus: etykieta + tokeny w `<data>/accounts/<slug>.json` (0600, zapis atomowy).

Hasła nigdy tu nie trafiają — logowanie odbywa się na stronie Lidla, add-on dostaje tylko
tokeny. Refresh token rotuje przy każdym odświeżeniu, więc zapis musi być atomowy.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client.auth import jwt_payload

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


@dataclass(frozen=True)
class Account:
    slug: str
    label: str
    access_token: str | None = None
    refresh_token: str | None = None

    @property
    def connected(self) -> bool:
        return bool(self.refresh_token)

    @property
    def access_expires(self) -> int | None:
        if not self.access_token:
            return None
        exp = jwt_payload(self.access_token).get("exp")
        return int(exp) if isinstance(exp, (int, float)) else None


def slugify(label: str) -> str:
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_label.lower()).strip("-")[:32].strip("-")
    if not slug:
        raise ValueError("empty_label")
    return slug


class AccountStore:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path(self, slug: str) -> Path:
        if not _SLUG.match(slug):
            raise KeyError(slug)
        return self._dir / f"{slug}.json"

    def _write(self, slug: str, data: dict[str, Any]) -> None:
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self._path(slug)
        tmp = path.with_suffix(".json.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def get(self, slug: str) -> Account:
        path = self._path(slug)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise KeyError(slug) from err
        return Account(
            slug=slug,
            label=str(data.get("label") or slug),
            access_token=data.get("access_token"),
            refresh_token=data.get("refresh_token"),
        )

    def list(self) -> list[Account]:
        if not self._dir.is_dir():
            return []
        accounts = []
        for path in sorted(self._dir.glob("*.json"), key=lambda p: p.stem):
            try:
                accounts.append(self.get(path.stem))
            except KeyError:
                continue
        return accounts

    def create(self, label: str) -> Account:
        label = label.strip()[:40]
        base = slugify(label)
        slug, n = base, 2
        while self._path(slug).exists():
            slug = f"{base[:29]}-{n}"
            n += 1
        self._write(slug, {"label": label})
        return Account(slug=slug, label=label)

    def save_tokens(self, slug: str, tokens: dict[str, str]) -> None:
        account = self.get(slug)
        self._write(
            slug,
            {
                "label": account.label,
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
            },
        )

    def delete(self, slug: str) -> None:
        self._path(slug).unlink(missing_ok=True)
