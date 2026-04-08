"""Spotify playback from a local labeled track pool (CSV) + EEG targets.

Does not call ``/v1/recommendations``. Picks tracks by feature-space distance to
``target_energy`` / ``target_valence`` / ``target_tempo`` from
:func:`neuro_features_to_recommendation_targets`.
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from typing import Optional, Set

import numpy as np

from src.music_gen.spotify_controller import (
    NeuroFeatures,
    SpotifyClient,
    neuro_features_to_recommendation_targets,
)
from src.music_gen.track_pool import TrackPool

logger = logging.getLogger(__name__)


def _pool_weights() -> tuple[float, float, float]:
    def wf(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, str(default)) or str(default))
        except ValueError:
            return default

    w_e = max(0.0, wf("SPOTIFY_POOL_WEIGHT_ENERGY", 1.0))
    w_v = max(0.0, wf("SPOTIFY_POOL_WEIGHT_VALENCE", 1.0))
    w_t = max(0.0, wf("SPOTIFY_POOL_WEIGHT_TEMPO", 0.85))
    if w_e + w_v + w_t < 1e-9:
        return 1.0, 1.0, 1.0
    return w_e, w_v, w_t


class SpotifyNeuroPoolController:
    """Periodically (or on mood change) play the nearest pool track to EEG-derived targets."""

    def __init__(self, spotify_client: SpotifyClient, pool: TrackPool) -> None:
        self._spotify = spotify_client
        self._pool = pool
        self._last_play_at: float = 0.0
        self._min_interval_s: float = float(
            os.environ.get("SPOTIFY_POOL_MIN_INTERVAL_S", "10") or "10"
        )
        self._min_interval_s = max(5.0, self._min_interval_s)
        try:
            self._top_k = int(os.environ.get("SPOTIFY_POOL_TOP_K", "8") or "8")
        except ValueError:
            self._top_k = 8
        self._top_k = max(1, min(self._top_k, 200))

        try:
            hist = int(os.environ.get("SPOTIFY_POOL_HISTORY", "24") or "24")
        except ValueError:
            hist = 24
        self._recent: deque[str] = deque(maxlen=max(3, min(hist, 500)))

        self._mood_gate = os.environ.get("SPOTIFY_POOL_ON_MOOD_CHANGE_ONLY", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        self._last_mood: Optional[str] = None
        self._rng = np.random.default_rng()

    def update(
        self,
        features: NeuroFeatures,
        device_id: Optional[str] = None,
        *,
        stable_mood: Optional[str] = None,
    ) -> None:
        if self._pool.size == 0:
            return

        now = time.time()
        if now - self._last_play_at < self._min_interval_s:
            return

        if self._mood_gate:
            mood = stable_mood
            if mood is None:
                return
            if mood == self._last_mood:
                return
            self._last_mood = mood

        targets = neuro_features_to_recommendation_targets(features)
        exclude: Set[str] = set(self._recent)
        uri = self._pool.pick_nearest(
            targets["target_energy"],
            targets["target_valence"],
            targets["target_tempo"],
            rng=self._rng,
            exclude=exclude,
            top_k=self._top_k,
            weights=_pool_weights(),
        )
        if not uri:
            return

        try:
            self._spotify.play_track_uris([uri], device_id=device_id)
        except Exception as exc:
            logger.warning("Spotify pool playback failed: %s", exc)
            return

        self._last_play_at = now
        self._recent.append(uri)
        logger.info(
            "Spotify pool track=%s targets e=%.2f v=%.2f tempo=%.0f mood=%s",
            uri,
            targets["target_energy"],
            targets["target_valence"],
            targets["target_tempo"],
            stable_mood or "-",
        )
