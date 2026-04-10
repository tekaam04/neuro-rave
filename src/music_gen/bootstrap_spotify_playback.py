"""Kick off Spotify playback once (e.g. after saving mood mapping from the Setup page)."""

from __future__ import annotations

import logging
from typing import Optional

import src.constants as const
from src.music_gen.spotify_controller import SpotifyClient
from src.music_gen.spotify_mapping_store import load_mood_playlists
from src.music_gen.spotify_refresh_token import load_spotify_refresh_token

logger = logging.getLogger(__name__)


def try_start_calm_context_playback() -> tuple[bool, Optional[str]]:
    """Start the calm playlist/album context if mapping + token exist."""
    tok = load_spotify_refresh_token()
    if not tok:
        return False, "no refresh token"

    m = load_mood_playlists()
    if not m or "calm" not in m or not m["calm"]:
        return False, "no calm URI in mapping"

    uri = m["calm"][0]
    try:
        client = SpotifyClient(
            const.SPOTIFY_CLIENT_ID,
            const.SPOTIFY_CLIENT_SECRET,
            tok,
        )
        client.start_playlist(uri)
        logger.info("Bootstrap playback started on calm context %s", uri[:48])
        return True, None
    except Exception as exc:
        logger.warning("Bootstrap playback failed: %s", exc)
        return False, str(exc)
