from __future__ import annotations

import base64
import logging
import os
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Log at most once per URI when track/album listing is forbidden (API restriction).
_context_track_list_blocked: set[str] = set()


@dataclass
class NeuroFeatures:
    """Container for EEG-derived features used to drive Spotify."""

    energy: float  # 0.0–1.0, rough arousal / activation
    focus: float  # 0.0–1.0, sustained attention / engagement


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def classify_mood(features: NeuroFeatures) -> str:
    """Map normalized features to a coarse 'mood' bucket.

    This is intentionally simple and deterministic so it can be
    iterated on quickly and tested in isolation.
    """
    energy = clamp(features.energy)

    if energy < 0.3:
        return "calm"
    if energy < 0.7:
        return "focus"
    return "hype"


class SpotifyClient:
    """Thin wrapper around the Spotify Web API for playback control.

    This client is intentionally minimal: it only covers the token
    refresh flow and the subset of endpoints needed for playback
    control in the neuro-rave context.
    """

    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE_URL = "https://api.spotify.com/v1"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _ensure_access_token(self) -> None:
        if self._access_token and time.time() < self._token_expires_at - 30:
            return

        auth_header = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode("utf-8")
        ).decode("utf-8")

        resp = requests.post(
            self.TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            headers={"Authorization": f"Basic {auth_header}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        self._access_token = data["access_token"]
        # "expires_in" is seconds from now.
        self._token_expires_at = time.time() + float(data.get("expires_in", 3600))

    def _headers(self) -> Dict[str, str]:
        self._ensure_access_token()
        if not self._access_token:
            raise RuntimeError("Failed to obtain Spotify access token.")
        return {"Authorization": f"Bearer {self._access_token}"}

    def get_devices(self) -> Dict:
        """Return the user's available playback devices."""
        resp = requests.get(
            f"{self.API_BASE_URL}/me/player/devices",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def set_shuffle(self, state: bool, device_id: Optional[str] = None) -> None:
        """Enable or disable shuffle for the current (or given) device."""
        params: Dict[str, str] = {"state": "true" if state else "false"}
        if device_id:
            params["device_id"] = device_id
        resp = requests.put(
            f"{self.API_BASE_URL}/me/player/shuffle",
            params=params,
            headers=self._headers(),
            timeout=10,
        )
        if resp.status_code not in (200, 204):
            raise RuntimeError(
                f"Spotify shuffle request failed: {resp.status_code} {resp.text}"
            )

    def get_context_track_total(self, context_uri: str) -> int:
        """Return track count for a ``spotify:playlist:`` or ``spotify:album:`` URI.

        Restricted catalogs may return **403** for metadata even when
        ``PUT /me/player/play`` with the same ``context_uri`` works; then returns
        ``0`` so callers can still play and use shuffle only.
        """
        if context_uri.startswith("spotify:playlist:"):
            pid = context_uri.split(":")[-1]
            resp = requests.get(
                f"{self.API_BASE_URL}/playlists/{pid}/tracks",
                params={"fields": "total", "limit": 1},
                headers=self._headers(),
                timeout=10,
            )
        elif context_uri.startswith("spotify:album:"):
            aid = context_uri.split(":")[-1]
            resp = requests.get(
                f"{self.API_BASE_URL}/albums/{aid}",
                params={"fields": "total_tracks"},
                headers=self._headers(),
                timeout=10,
            )
        else:
            logger.warning(
                "Unsupported Spotify context for track count: %s "
                "(use spotify:playlist: or spotify:album:)",
                context_uri,
            )
            return 0

        if resp.status_code in (401, 403, 404):
            if context_uri not in _context_track_list_blocked:
                _context_track_list_blocked.add(context_uri)
                logger.warning(
                    "Cannot read track count (%s) for %s; "
                    "random start offset skipped. Playback via context_uri may still work.",
                    resp.status_code,
                    context_uri,
                )
            return 0
        resp.raise_for_status()
        data = resp.json()
        if context_uri.startswith("spotify:album:"):
            return int(data.get("total_tracks", 0))
        return int(data.get("total", 0))

    def start_playlist(
        self,
        context_uri: str,
        device_id: Optional[str] = None,
    ) -> None:
        """Start or transfer playback of a playlist or album (``context_uri``).

        If device_id is None, Spotify chooses the currently active
        device, or fails if none is available.

        With shuffle on (default, ``SPOTIFY_SHUFFLE`` unset or truthy), requests a
        random start offset when the Web API exposes a track count; otherwise starts
        at the default first track, then enables API shuffle where supported.
        """
        params: Dict[str, str] = {}
        if device_id:
            params["device_id"] = device_id

        use_shuffle = os.environ.get("SPOTIFY_SHUFFLE", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

        body: Dict[str, Any] = {"context_uri": context_uri}
        if use_shuffle:
            total = self.get_context_track_total(context_uri)
            if total > 0:
                body["offset"] = {"position": random.randrange(total)}

        resp = requests.put(
            f"{self.API_BASE_URL}/me/player/play",
            params=params,
            json=body,
            headers=self._headers(),
            timeout=10,
        )
        # 204 is success with no content.
        if resp.status_code not in (200, 204):
            # Surface useful error information to callers.
            raise RuntimeError(
                f"Spotify playback request failed: {resp.status_code} {resp.text}"
            )

        if use_shuffle:
            self.set_shuffle(True, device_id=device_id)


class SpotifyNeuroController:
    """Map NeuroFeatures to Spotify playback behavior."""

    def __init__(
        self,
        spotify_client: SpotifyClient,
        mood_playlists: Dict[str, List[str]],
    ) -> None:
        """
        Args:
            spotify_client: Authenticated SpotifyClient instance.
            mood_playlists: Mapping from mood labels (e.g. 'calm',
                'focus', 'hype') to one or more Spotify ``playlist`` / ``album`` URIs.
                When a mood has multiple URIs, the active one is chosen using
                ``SPOTIFY_MOOD_CONTEXT_MODE`` (see :meth:`_pick_context_uri`).
        """
        self._spotify = spotify_client
        self._mood_playlists = mood_playlists
        self._current_mood: Optional[str] = None
        self._last_switch_at: float = 0.0
        # Minimum seconds between playlist changes to avoid rapid switching.
        # Can be overridden via env var; default keeps each choice for ~60s.
        self._min_switch_s: float = float(os.environ.get("SPOTIFY_MIN_SWITCH_S", "60") or "60")
        mode = os.environ.get("SPOTIFY_MOOD_CONTEXT_MODE", "random").strip().lower()
        if mode not in ("random", "round_robin", "first"):
            mode = "random"
        self._context_pick_mode = mode
        self._round_robin_index: dict[str, int] = defaultdict(int)

    def _pick_context_uri(self, mood: str) -> Optional[str]:
        choices = self._mood_playlists.get(mood) or []
        if not choices:
            return None
        if len(choices) == 1 or self._context_pick_mode == "first":
            return choices[0]
        if self._context_pick_mode == "round_robin":
            i = self._round_robin_index[mood] % len(choices)
            self._round_robin_index[mood] += 1
            return choices[i]
        return random.choice(choices)

    def update(self, features: NeuroFeatures, device_id: Optional[str] = None) -> None:
        """Update Spotify playback based on the latest features.

        This function is intended to be called from the real-time EEG
        pipeline whenever a new window of features is available.

        It is deliberately conservative: it only changes the playlist
        when the inferred mood bucket changes, to avoid thrashing.
        """
        mood = classify_mood(features)

        if mood == self._current_mood:
            return

        now = time.time()
        if self._last_switch_at and (now - self._last_switch_at) < self._min_switch_s:
            return

        context_uri = self._pick_context_uri(mood)
        if not context_uri:
            return

        self._spotify.start_playlist(context_uri, device_id=device_id)
        self._current_mood = mood
        self._last_switch_at = now

