from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Dict, Optional

import requests


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

    def start_playlist(
        self,
        playlist_uri: str,
        device_id: Optional[str] = None,
    ) -> None:
        """Start or transfer playback of a playlist on a device.

        If device_id is None, Spotify chooses the currently active
        device, or fails if none is available.
        """
        params: Dict[str, str] = {}
        if device_id:
            params["device_id"] = device_id

        body = {"context_uri": playlist_uri}

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


class SpotifyNeuroController:
    """Map NeuroFeatures to Spotify playback behavior."""

    def __init__(
        self,
        spotify_client: SpotifyClient,
        mood_playlists: Dict[str, str],
    ) -> None:
        """
        Args:
            spotify_client: Authenticated SpotifyClient instance.
            mood_playlists: Mapping from mood labels (e.g. 'calm',
                'focus', 'hype') to Spotify playlist URIs.
        """
        self._spotify = spotify_client
        self._mood_playlists = mood_playlists
        self._current_mood: Optional[str] = None

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

        playlist_uri = self._mood_playlists.get(mood)
        if not playlist_uri:
            # No playlist configured for this mood; do nothing.
            return

        self._spotify.start_playlist(playlist_uri, device_id=device_id)
        self._current_mood = mood

