"""Punkt wejścia add-onu: panel Ingress na porcie 8099."""

from __future__ import annotations

import logging

import uvicorn

from .settings import load_settings
from .web.app import create_app


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    uvicorn.run(
        create_app(settings), host="0.0.0.0", port=8099, log_level=settings.log_level, access_log=False
    )


if __name__ == "__main__":
    main()
