"""Dashboard-selected Spotify pause lock persisted in config.

When paused is true, neuro-driven playback updates are blocked until resumed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_dir() -> Path:
    return _project_root() / "config"


def dashboard_playback_pause_path() -> Path:
    return _config_dir() / "dashboard_spotify_pause_state.json"


def read_dashboard_playback_paused() -> bool:
    path = dashboard_playback_pause_path()
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return bool((raw or {}).get("paused", False))
    except Exception as exc:
        logger.warning("Failed to read dashboard pause state (%s): %s", path, exc)
        return False


def write_dashboard_playback_paused(paused: bool) -> bool:
    path = dashboard_playback_pause_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"paused": bool(paused)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return bool(paused)
