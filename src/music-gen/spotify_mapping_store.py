"""Persist calm/focus/hype Spotify playlist URIs to config/spotify_mood_mapping.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_MAPPING_FILE = "spotify_mood_mapping.json"


def _project_config_dir() -> Path:
    # src/music_gen/ -> src/ -> project root
    return Path(__file__).resolve().parent.parent.parent / "config"


def mood_mapping_path() -> Path:
    return _project_config_dir() / _MAPPING_FILE


def load_mood_playlists() -> dict[str, str] | None:
    path = mood_mapping_path()
    if not path.exists():
        return None
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    out: dict[str, str] = {}
    for k in ("calm", "focus", "hype"):
        v = data.get(k)
        if isinstance(v, str) and v.startswith("spotify:playlist:"):
            out[k] = v
    if len(out) == 3:
        return out
    return None


def save_mood_playlists(mapping: dict[str, str], *, user_id: str = "default") -> dict[str, Any]:
    path = mood_mapping_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "user_id": user_id,
        "calm_uri": mapping["calm"],
        "focus_uri": mapping["focus"],
        "hype_uri": mapping["hype"],
        "calm": mapping["calm"],
        "focus": mapping["focus"],
        "hype": mapping["hype"],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def resolve_mood_playlists() -> dict[str, str] | None:
    m = load_mood_playlists()
    if m:
        return m
    calm = os.environ.get("SPOTIFY_PLAYLIST_CALM")
    focus = os.environ.get("SPOTIFY_PLAYLIST_FOCUS")
    hype = os.environ.get("SPOTIFY_PLAYLIST_HYPE")
    if calm and focus and hype:
        return {"calm": calm, "focus": focus, "hype": hype}
    
    # Fallback to constants from config/constants.json
    try:
        from src.constants import SPOTIFY_PLAYLIST_CALM, SPOTIFY_PLAYLIST_FOCUS, SPOTIFY_PLAYLIST_HYPE
        return {
            "calm": SPOTIFY_PLAYLIST_CALM,
            "focus": SPOTIFY_PLAYLIST_FOCUS,
            "hype": SPOTIFY_PLAYLIST_HYPE,
        }
    except ImportError:
        return None
