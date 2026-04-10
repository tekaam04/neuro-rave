"""Resolve Spotify refresh token: ``SPOTIFY_REFRESH_TOKEN`` env, else ``config/.spotify_refresh_token``."""

from __future__ import annotations

import os
from pathlib import Path


def _config_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "config"


def refresh_token_file_path() -> Path:
    return _config_dir() / ".spotify_refresh_token"


def load_spotify_refresh_token() -> str:
    env = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()
    if env:
        return env
    path = refresh_token_file_path()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def save_spotify_refresh_token_to_file(token: str) -> Path:
    path = refresh_token_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip(), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
