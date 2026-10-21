"""Indlæsning af konfigurationsfiler fra config/."""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import Source

CONFIG_DIR = Path("config")


def load_settings(path: Path | None = None) -> dict:
    with open(path or CONFIG_DIR / "gulvmaatten.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources(path: Path | None = None) -> list[Source]:
    with open(path or CONFIG_DIR / "sources.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [Source.from_config(d) for d in data.get("kilder", [])]
