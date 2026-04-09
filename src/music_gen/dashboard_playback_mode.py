"""Dashboard-selected Spotify playback mode (context / playlist vs pool), persisted next to other config."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

Mode = Literal["context", "pool"]

_deprecated_recommendations_warned = False


def _warn_deprecated_recommendations() -> None:
    global _deprecated_recommendations_warned
    if _deprecated_recommendations_warned:
        return
    _deprecated_recommendations_warned = True
    logger.warning(
        "Playback mode 'recommendations' is no longer supported; using playlist/context instead.",
    )


def _config_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "config"


def dashboard_playback_mode_path() -> Path:
    return _config_dir() / "dashboard_spotify_playback_mode.json"


def read_dashboard_playback_mode() -> Mode:
    """File overrides ``SPOTIFY_PLAYBACK_MODE`` when present and valid."""
    path = dashboard_playback_mode_path()
    if path.is_file():
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = str(data.get("mode", "")).strip().lower()
                if raw in ("playlist", "context"):
                    return "context"
                if raw == "pool":
                    return "pool"
                if raw == "recommendations":
                    _warn_deprecated_recommendations()
                    return "context"
        except (OSError, json.JSONDecodeError):
            pass
    em = os.environ.get("SPOTIFY_PLAYBACK_MODE", "context").strip().lower()
    if em in ("playlist", "context"):
        return "context"
    if em == "pool":
        return "pool"
    if em == "recommendations":
        _warn_deprecated_recommendations()
        return "context"
    return "context"


def write_dashboard_playback_mode(mode: str) -> Mode:
    """Persist ``context`` (playlist) or ``pool``."""
    m = str(mode).strip().lower()
    if m in ("playlist", "context"):
        norm: Mode = "context"
    elif m == "pool":
        norm = "pool"
    else:
        raise ValueError(f"unsupported playback mode: {mode!r}")

    path = dashboard_playback_mode_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mode": norm}, indent=2), encoding="utf-8")
    return norm
