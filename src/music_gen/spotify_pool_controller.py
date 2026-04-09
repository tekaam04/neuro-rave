"""Spotify playback from a local labeled track pool (CSV) + EEG targets.

Picks tracks by feature-space distance to ``target_energy`` / ``target_valence`` /
``target_tempo`` from :func:`neuro_features_to_pool_targets`.
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
    neuro_features_to_pool_targets,
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
        # Match playlist-mode guardrail: never switch faster than 10s.
        self._min_interval_s = max(10.0, self._min_interval_s)
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
        self._invalid_uris: Set[str] = set()
        self._validated_uris: Set[str] = set()
        self._next_validate_at: float = 0.0
        try:
            self._validate_batch = int(
                os.environ.get("SPOTIFY_POOL_VALIDATE_BATCH", "50") or "50"
            )
        except ValueError:
            self._validate_batch = 50
        self._validate_batch = max(1, min(self._validate_batch, 200))
        self._current_track_id: Optional[str] = None
        self._last_end_trigger_at: float = 0.0
        self._last_forced_switch_at: float = 0.0
        self._last_seen_mood: Optional[str] = None
        self._near_end_threshold: float = float(
            os.environ.get("SPOTIFY_POOL_NEAR_END_THRESHOLD", "0.97") or "0.97"
        )
        self._near_end_threshold = max(0.8, min(self._near_end_threshold, 0.995))
        self._end_debounce_s: float = float(
            os.environ.get("SPOTIFY_POOL_END_DEBOUNCE_S", "3") or "3"
        )
        self._urgent_hold_s: float = float(
            os.environ.get("SPOTIFY_POOL_URGENT_HOLD_S", "20") or "20"
        )
        self._urgent_switch_enabled: bool = os.environ.get(
            "SPOTIFY_POOL_URGENT_SWITCH", "1"
        ).strip().lower() in ("1", "true", "yes")

    def _validate_pool_slice(self, now: float) -> None:
        """Gradually validate pool track availability and blacklist dead URIs."""
        if now < self._next_validate_at or self._pool.size == 0:
            return
        self._next_validate_at = now + 30.0
        candidates: list[str] = []
        for raw in self._pool.uris:
            uri = str(raw)
            if uri in self._validated_uris or uri in self._invalid_uris:
                continue
            candidates.append(uri)
            if len(candidates) >= self._validate_batch:
                break
        if not candidates:
            return
        try:
            playable = self._spotify.get_playable_track_uris(candidates)
        except Exception as exc:
            logger.debug("Pool validation skipped this cycle: %s", exc)
            return
        self._validated_uris.update(candidates)
        bad = [u for u in candidates if u not in playable]
        if bad:
            self._invalid_uris.update(bad)
            logger.info(
                "Spotify pool pruned %d unavailable tracks (total invalid=%d).",
                len(bad),
                len(self._invalid_uris),
            )

    def _should_switch_on_track_end(self, now: float) -> bool:
        if now - self._last_end_trigger_at < self._end_debounce_s:
            return False
        state = self._spotify.get_player_state()
        if not state:
            return False
        item = state.get("item") if isinstance(state.get("item"), dict) else None
        if not item:
            return False
        track_id = str(item.get("id") or "")
        duration = int(item.get("duration_ms") or 0)
        progress = int(state.get("progress_ms") or 0)
        if track_id:
            self._current_track_id = track_id
        if duration <= 0:
            return False
        near_end = (progress / duration) >= self._near_end_threshold
        if not near_end:
            return False
        self._last_end_trigger_at = now
        return True

    def _should_force_urgent_switch(self, now: float, stable_mood: Optional[str]) -> bool:
        if not self._urgent_switch_enabled or stable_mood is None:
            return False
        if self._last_seen_mood is None:
            self._last_seen_mood = stable_mood
            return False
        mood_changed = stable_mood != self._last_seen_mood
        self._last_seen_mood = stable_mood
        if not mood_changed:
            return False
        if now - self._last_play_at < self._urgent_hold_s:
            return False
        if now - self._last_forced_switch_at < self._urgent_hold_s:
            return False
        self._last_forced_switch_at = now
        return True

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
        self._validate_pool_slice(now)
        end_trigger = self._should_switch_on_track_end(now)
        urgent_trigger = self._should_force_urgent_switch(now, stable_mood)

        if not end_trigger and not urgent_trigger:
            # Safety fallback in case player-state polling is stale.
            if now - self._last_play_at < max(30.0, self._min_interval_s):
                return

            if self._mood_gate:
                mood = stable_mood
                if mood is None:
                    return
                if mood == self._last_mood:
                    return
                self._last_mood = mood

        targets = neuro_features_to_pool_targets(features)
        for _ in range(3):
            exclude: Set[str] = set(self._recent) | self._invalid_uris
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

            # Validate selected URI right before playback to avoid silent dead tracks.
            if uri not in self._validated_uris and uri not in self._invalid_uris:
                try:
                    playable = self._spotify.get_playable_track_uris([uri])
                except Exception as exc:
                    logger.debug("On-demand pool URI validation failed: %s", exc)
                    playable = {uri}
                self._validated_uris.add(uri)
                if uri not in playable:
                    self._invalid_uris.add(uri)
                    continue

            try:
                smooth = os.environ.get("SPOTIFY_SMOOTH_TRANSITIONS", "1").strip().lower() not in (
                    "0",
                    "false",
                    "no",
                    "off",
                )
                if smooth:
                    self._spotify.play_track_uris_smooth([uri], device_id=device_id)
                else:
                    self._spotify.play_track_uris([uri], device_id=device_id)
            except Exception as exc:
                # Playback failure for a single URI often means unavailable item.
                self._invalid_uris.add(uri)
                logger.warning("Spotify pool playback failed for %s: %s", uri, exc)
                continue

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
            return
