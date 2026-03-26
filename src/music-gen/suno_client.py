from __future__ import annotations

"""
Suno-based music generation driven by EEG features.

This module provides:

* A simple mapping from NeuroFeatures to high-level Suno generation parameters.
* A minimal HTTP client for the Suno API (create generation + query
  generation status).

The concrete API shape (base URL, auth header name, request/response
schemas) may need to be adjusted to match the deployed Suno backend.
"""

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
    ...
    """
    energy = clamp(features.energy)
    if energy < 0.3:
        return "calm"
    if energy < 0.7:
        return "focus"
    return "hype"


@dataclass
class SunoConfig:
    """High-level configuration for a single Suno generation request."""

    prompt: str
    style: Optional[str] = None
    model: Optional[str] = None
    duration_seconds: Optional[int] = None


def features_to_suno_config(features: NeuroFeatures) -> SunoConfig:
    """Map normalized EEG features to a Suno generation config.

    This is intentionally simple and deterministic so it can be
    iterated on quickly. It uses the same coarse mood buckets as the
    Spotify controller, but turns them into text prompts and styles
    suitable for Suno.
    """
    mood = classify_mood(features)
    energy = clamp(features.energy)

    if mood == "calm":
        prompt = "slow, spacious ambient electronic track with soft pads and gentle textures"
        style = "ambient electronic"
        duration = 60
    elif mood == "focus":
        prompt = "steady, minimal electronic track for deep focus, subtle rhythmic patterns, no vocals"
        style = "minimal techno / lofi electronic"
        duration = 90
    else:  # "hype"
        prompt = "high energy techno track with pulsing bass and driving drums, club-ready, no vocals"
        style = "techno / peak-time"
        duration = 90

    # Optionally nudge duration by energy (more energy → slightly longer).
    duration = int(duration + 30 * energy)

    return SunoConfig(
        prompt=prompt,
        style=style,
        model=None,
        duration_seconds=duration,
    )


class SunoClient:
    """Minimal HTTP client for the Suno music generation API.

    This client assumes:
      * API key auth via an HTTP header (default 'X-API-KEY').
      * A base URL exposing:
          POST /suno/generate-music         -> { "generation_id": "..." }
          GET  /suno/generations/{id}      -> generation status/details

    Adjust endpoint paths and payload schemas to match the actual Suno
    deployment or wrapper you are using.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.sunoapi.org",
        api_key_header: str = "X-API-KEY",
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._api_key_header = api_key_header

    def _headers(self) -> Dict[str, str]:
        return {
            self._api_key_header: self._api_key,
            "Content-Type": "application/json",
        }

    def create_generation(self, config: SunoConfig) -> str:
        """Kick off a new music generation request.

        Returns:
            A generation identifier that can be used with
            get_generation_details to poll for completion and retrieve
            audio URLs.
        """
        payload: Dict[str, object] = {
            "prompt": config.prompt,
        }
        if config.style:
            payload["style"] = config.style
        if config.model:
            payload["model"] = config.model
        if config.duration_seconds:
            payload["duration_seconds"] = config.duration_seconds

        resp = requests.post(
            f"{self._base_url}/suno/generate-music",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        generation_id = data.get("generation_id")
        if not generation_id:
            raise RuntimeError(f"Suno API did not return generation_id: {data}")
        return str(generation_id)

    def get_generation_details(self, generation_id: str) -> Dict:
        """Fetch details (including audio URLs) for a generation."""
        resp = requests.get(
            f"{self._base_url}/suno/generations/{generation_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


class SunoNeuroController:
    """Bridge EEG features to Suno music generation requests.

    This controller is intentionally "episodic": instead of trying to
    control every bar of music in real time, it periodically decides on
    a new track configuration based on recent features and triggers a
    new Suno generation.
    """

    def __init__(self, client: SunoClient) -> None:
        self._client = client
        self._last_generation_id: Optional[str] = None

    @property
    def last_generation_id(self) -> Optional[str]:
        return self._last_generation_id

    def request_new_track(self, features: NeuroFeatures) -> str:
        """Create a new Suno generation based on current features.

        Upstream code is responsible for:
          * Deciding when to call this (e.g. every N seconds or after a
            mood transition).
          * Polling get_generation_details on the returned ID and
            handing the resulting audio URLs to the playback layer.
        """
        config = features_to_suno_config(features)
        generation_id = self._client.create_generation(config)
        self._last_generation_id = generation_id
        return generation_id

