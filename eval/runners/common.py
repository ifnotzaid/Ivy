"""Shared helpers for evaluation runners."""

from __future__ import annotations

import json
import time
from importlib import import_module
from pathlib import Path
from typing import Any


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[index]


def sleep_between_calls(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def require_dependency(import_name: str, package_name: str | None = None) -> Any:
    try:
        return import_module(import_name)
    except ImportError as exc:
        package = package_name or import_name
        raise RuntimeError(f"Missing dependency '{package}'. Install it with: pip install {package}") from exc


def normalize_label(value: str) -> str:
    return str(value or "").strip().lower()
