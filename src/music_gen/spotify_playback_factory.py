"""Build the active Spotify neuro controller for a playback mode."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Union

from src.music_gen.spotify_controller import SpotifyClient, SpotifyNeuroController
from src.music_gen.spotify_mapping_store import resolve_mood_playlists
from src.music_gen.spotify_pool_controller import SpotifyNeuroPoolController
from src.music_gen.track_pool import TrackPool

logger = logging.getLogger(__name__)

SpotifyPlaybackController = Union[SpotifyNeuroController, SpotifyNeuroPoolController]


def build_playback_controller(
    playback_mode: str,
    *,
    spotify: SpotifyClient,
    project_root: Path,
) -> SpotifyPlaybackController | None:
    m = playback_mode.strip().lower()
    if m in ("playlist", "context"):
        mood_playlists = resolve_mood_playlists()
        if not mood_playlists:
            logger.warning(
                "Spotify context mode: no mood playlists (mapping file + env + constants) — disabled until configured.",
            )
            return None
        logger.info("Spotify playlist/context mode enabled.")
        return SpotifyNeuroController(spotify, mood_playlists)

    if m == "pool":
        csv_path = (
            os.environ.get("SPOTIFY_TRACK_POOL_CSV", "").strip()
            or str(project_root / "config" / "track_pool.csv")
        )
        pool = TrackPool.from_csv(csv_path)
        if pool.size == 0:
            logger.warning(
                "Spotify pool mode: no tracks in %s — pool controller disabled.",
                csv_path,
            )
            return None
        logger.info(
            "Spotify track-pool mode enabled (%d tracks, CSV=%s).",
            pool.size,
            csv_path,
        )
        return SpotifyNeuroPoolController(spotify, pool)

    logger.warning("Unknown playback mode %r — Spotify disabled.", playback_mode)
    return None
