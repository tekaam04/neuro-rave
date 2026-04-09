"""Persist calm/focus/hype Spotify context URIs (playlist or album) to config/spotify_mood_mapping.json."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

_MAPPING_FILE = "spotify_mood_mapping.json"


def _project_config_dir() -> Path:
    # src/music_gen/ -> src/ -> project root
    return Path(__file__).resolve().parent.parent.parent / "config"


def mood_mapping_path() -> Path:
    return _project_config_dir() / _MAPPING_FILE


def _is_valid_spotify_context_uri(s: str) -> bool:
    t = s.strip()
    return t.startswith("spotify:playlist:") or t.startswith("spotify:album:")


_SPOTIFY_OPEN_RE = re.compile(
    r"^https?://open\.spotify\.com/(playlist|album)/([a-zA-Z0-9]+)(?:\?.*)?$",
    re.IGNORECASE,
)


def parse_spotify_context_input(raw: str) -> str | None:
    """Accept ``spotify:playlist:`` / ``spotify:album:`` URIs or open.spotify.com playlist/album URLs."""
    s = raw.strip()
    if _is_valid_spotify_context_uri(s):
        return s.strip()
    m = _SPOTIFY_OPEN_RE.match(s)
    if m:
        kind, pid = m.group(1).lower(), m.group(2)
        return f"spotify:{kind}:{pid}"
    return None


def normalize_context_uris(raw: Any) -> list[str] | None:
    """Parse env / JSON value into a non-empty list of playlist or album URIs.

    Accepts a single URI string, comma-separated URIs (no commas inside Spotify URIs),
    or a JSON array of URI strings.
    """
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        uris = [p for p in parts if _is_valid_spotify_context_uri(p)]
        return uris if uris else None
    if isinstance(raw, list):
        uris = [
            x.strip()
            for x in raw
            if isinstance(x, str) and _is_valid_spotify_context_uri(x.strip())
        ]
        return uris if uris else None
    return None


def load_mood_playlists() -> dict[str, list[str]] | None:
    path = mood_mapping_path()
    if not path.exists():
        return None
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    out: dict[str, list[str]] = {}
    for k in ("calm", "focus", "hype"):
        v = data.get(k)
        uris = normalize_context_uris(v)
        if uris:
            out[k] = uris
    if not all(k in out for k in ("calm", "focus", "hype")):
        return None
    for k in ("deep_focus",):
        v = data.get(k)
        uris = normalize_context_uris(v)
        if uris:
            out[k] = uris
    return out


def save_mood_playlists(
    mapping: dict[str, str | Sequence[str]],
    *,
    user_id: str = "default",
) -> dict[str, Any]:
    norm: dict[str, list[str]] = {}
    for mood in ("calm", "focus", "hype"):
        raw = mapping[mood]
        if isinstance(raw, str):
            lst = normalize_context_uris(raw)
            if not lst:
                lst = [raw] if _is_valid_spotify_context_uri(raw) else []
        else:
            lst = [u for u in raw if isinstance(u, str) and _is_valid_spotify_context_uri(u)]
        if not lst:
            raise ValueError(f"no valid Spotify URIs for mood {mood!r}")
        norm[mood] = lst

    path = mood_mapping_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"user_id": user_id}
    for mood in ("calm", "focus", "hype"):
        lst = norm[mood]
        payload[f"{mood}_uri"] = lst[0]
        payload[mood] = lst if len(lst) > 1 else lst[0]

    df_raw = mapping.get("deep_focus")
    if df_raw is not None and df_raw != "":
        if isinstance(df_raw, str):
            dfl = normalize_context_uris(df_raw)
            if not dfl and _is_valid_spotify_context_uri(df_raw):
                dfl = [df_raw.strip()]
        elif isinstance(df_raw, list):
            dfl = [
                u for u in df_raw
                if isinstance(u, str) and _is_valid_spotify_context_uri(u)
            ]
        else:
            dfl = []
        if dfl:
            payload["deep_focus"] = dfl[0] if len(dfl) == 1 else dfl

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def resolve_mood_playlists() -> dict[str, list[str]] | None:
    m = load_mood_playlists()
    if m:
        return m
    calm = os.environ.get("SPOTIFY_PLAYLIST_CALM")
    focus = os.environ.get("SPOTIFY_PLAYLIST_FOCUS")
    hype = os.environ.get("SPOTIFY_PLAYLIST_HYPE")
    if calm and focus and hype:
        c, f, h = (
            normalize_context_uris(calm),
            normalize_context_uris(focus),
            normalize_context_uris(hype),
        )
        if c and f and h:
            out: dict[str, list[str]] = {"calm": c, "focus": f, "hype": h}
            df_env = os.environ.get("SPOTIFY_PLAYLIST_DEEP_FOCUS", "").strip()
            if df_env:
                dfl = normalize_context_uris(df_env)
                if dfl:
                    out["deep_focus"] = dfl
            return out

    try:
        from src.constants import (
            SPOTIFY_PLAYLIST_CALM,
            SPOTIFY_PLAYLIST_DEEP_FOCUS,
            SPOTIFY_PLAYLIST_FOCUS,
            SPOTIFY_PLAYLIST_HYPE,
        )

        c = normalize_context_uris(SPOTIFY_PLAYLIST_CALM)
        f = normalize_context_uris(SPOTIFY_PLAYLIST_FOCUS)
        h = normalize_context_uris(SPOTIFY_PLAYLIST_HYPE)
        if c and f and h:
            out = {"calm": c, "focus": f, "hype": h}
            dfl = normalize_context_uris(SPOTIFY_PLAYLIST_DEEP_FOCUS)
            if dfl:
                out["deep_focus"] = dfl
            return out
    except ImportError:
        return None
    return None
