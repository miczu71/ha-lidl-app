"""Ustawienia add-onu: opcje z /data/options.json (Supervisor) + zmienne środowiskowe dev."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path

COUNTRY = "PL"
LANGUAGE = "pl-PL"
DEFAULT_RUN_TIME = time(7, 0)  # jak w config.yaml


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    log_level: str
    dev: bool
    auto_activate: bool = False
    run_time: time = DEFAULT_RUN_TIME

    @property
    def accounts_dir(self) -> Path:
        return self.data_dir / "accounts"


def load_settings() -> Settings:
    options_path = Path(os.environ.get("LIDL_OPTIONS_PATH", "/data/options.json"))
    options: dict[str, object] = {}
    try:
        options = json.loads(options_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return Settings(
        data_dir=Path(os.environ.get("LIDL_DATA_DIR", "/data")),
        log_level=str(options.get("log_level", "info")),
        dev=os.environ.get("LIDL_DEV") == "1",
        auto_activate=options.get("auto_activate") is True,
        run_time=(  # format HH:MM pilnuje schema w config.yaml
            time.fromisoformat(str(options["run_time"])) if "run_time" in options else DEFAULT_RUN_TIME
        ),
    )
