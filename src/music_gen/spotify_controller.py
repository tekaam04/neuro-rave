from __future__ import annotations

import base64
import logging
import os
import random
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

import src.constants as const

logger = logging.getLogger(__name__)

# Log at most once per URI when track/album listing is forbidden (API restriction).
_context_track_list_blocked: set[str] = set()

# Throttle "no Spotify devices" warnings (main loop calls playback often).
_spotify_no_device_warn_at: float = 0.0
_spotify_rec_hint_at: float = 0.0


def _throttled_recommendations_hint(status: int, body: str, params: Dict[str, Any]) -> None:
    """Explain common 404 causes for GET /recommendations (logged at most once per minute)."""
    global _spotify_rec_hint_at
    now = time.time()
    if now - _spotify_rec_hint_at < 60.0:
        return
    _spotify_rec_hint_at = now
    safe_params = {k: v for k, v in params.items()}
    logger.warning(
        "Spotify GET /recommendations failed (%s). Response: %s. Params were: %s. "
        "Fixes: exact lowercase seeds from Spotify available-genre-seeds; "
        "SPOTIFY_MARKET=US (or your region). Some developer apps return 404 here; "
        "then use SPOTIFY_PLAYBACK_MODE=context.",
        status,
        (body or "").strip() or "(empty)",
        safe_params,
    )


@dataclass
class NeuroFeatures:
    """Container for EEG-derived features used to drive Spotify."""

    energy: float  # 0.0–1.0, rough arousal / activation
    focus: float  # 0.0–1.0, sustained attention / engagement
    # Rate of change of smoothed energy (per processing window); used in 2D mood rules.
    d_energy: float = 0.0


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def neuro_features_to_recommendation_targets(features: NeuroFeatures) -> Dict[str, float]:
    """Map EEG-derived scalars to Spotify recommendation target_* parameters.

    Spotify expects ``target_energy`` and ``target_valence`` in ``[0, 1]``;
    ``target_tempo`` is a BPM float (not normalized).
    """
    e = clamp(features.energy)
    fo = clamp(features.focus)
    target_energy = e
    # Blend: higher focus nudges valence up (engagement); energy adds arousal.
    target_valence = clamp(0.15 + 0.35 * e + 0.5 * fo)
    tempo_lo = float(os.environ.get("SPOTIFY_TARGET_TEMPO_MIN", "72") or "72")
    tempo_hi = float(os.environ.get("SPOTIFY_TARGET_TEMPO_MAX", "148") or "148")
    target_tempo = tempo_lo + e * (tempo_hi - tempo_lo)
    return {
        "target_energy": target_energy,
        "target_valence": target_valence,
        "target_tempo": target_tempo,
    }


# Optional URI list for a mood label; falls back to related keys (e.g. deep_focus → focus).
_MOOD_PLAYLIST_FALLBACK: Dict[str, str] = {
    "deep_focus": "focus",
}


def resolve_playlist_choices(mood: str, mood_playlists: Dict[str, List[str]]) -> List[str]:
    """Return playlist/album URI list for ``mood``, with fallback (``deep_focus`` → ``focus``)."""
    choices = mood_playlists.get(mood) or []
    if choices:
        return choices
    fb = _MOOD_PLAYLIST_FALLBACK.get(mood)
    if fb:
        return mood_playlists.get(fb) or []
    return []


def propose_mood(features: NeuroFeatures) -> str:
    """Map ``(energy, focus)`` and optional ``d_energy`` to a mood bucket.

    Buckets: ``calm``, ``deep_focus``, ``focus``, ``hype``. ``deep_focus`` uses the
    same playlist URIs as ``focus`` unless you add a ``deep_focus`` entry to the mapping.
    """
    e = clamp(features.energy)
    f = clamp(features.focus)
    d_e = float(getattr(features, "d_energy", 0.0) or 0.0)
    d_e = max(-1.0, min(1.0, d_e))
    # Rising energy nudges toward hype without requiring absolute level.
    scale = float(const.MOOD_D_ENERGY_SCALE)
    e_eff = clamp(e + scale * max(0.0, d_e))

    if e_eff >= float(const.MOOD_HYPE_E_EFF_MIN):
        return "hype"
    if e < float(const.MOOD_CALM_E_MAX) and f < float(const.MOOD_CALM_F_MAX):
        return "calm"
    if e < float(const.MOOD_DEEP_FOCUS_E_MAX) and f >= float(const.MOOD_DEEP_FOCUS_F_MIN):
        return "deep_focus"
    if e >= float(const.MOOD_DISTRACT_HYPE_E_MIN) and f < float(const.MOOD_DISTRACT_HYPE_F_MAX):
        return "hype"
    return "focus"


def classify_mood(features: NeuroFeatures) -> str:
    """Alias for :func:`propose_mood` (same 2D + ``d_energy`` logic)."""
    return propose_mood(features)


class MoodStabilizer:
    """EMA on energy/focus plus optional majority vote over recent proposed moods."""

    def __init__(self) -> None:
        self._ema_e: Optional[float] = None
        self._ema_f: Optional[float] = None
        self._prev_ema_e: Optional[float] = None
        alpha = float(os.environ.get("SPOTIFY_MOOD_EMA_ALPHA", "0.32") or "0.32")
        self._alpha = max(0.02, min(alpha, 0.9))
        try:
            n = int(os.environ.get("SPOTIFY_MOOD_VOTE_WINDOWS", "10") or "10")
        except ValueError:
            n = 10
        self._vote_maxlen = max(3, min(n, 120))
        self._votes: deque[str] = deque(maxlen=self._vote_maxlen)
        self._last_resolved: Optional[str] = None
        self._vote_off = os.environ.get("SPOTIFY_MOOD_VOTE_OFF", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )

    def smooth(self, energy: float, focus: float) -> tuple[float, float, float]:
        """Return ``(ema_energy, ema_focus, d_energy)``."""
        e = clamp(energy)
        f = clamp(focus)
        if self._ema_e is None:
            self._ema_e, self._ema_f = e, f
        else:
            a = self._alpha
            self._ema_e = a * e + (1 - a) * self._ema_e
            self._ema_f = a * f + (1 - a) * self._ema_f
        d_e = 0.0 if self._prev_ema_e is None else (self._ema_e - self._prev_ema_e)
        self._prev_ema_e = self._ema_e
        return self._ema_e, self._ema_f, d_e

    def majority_mood(self, proposed: str) -> str:
        """Stabilize ``proposed`` over the last N windows (mode); ties keep previous."""
        if self._vote_off:
            self._last_resolved = proposed
            return proposed
        self._votes.append(proposed)
        cnt = Counter(self._votes)
        ranked = cnt.most_common(2)
        if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
            return self._last_resolved if self._last_resolved is not None else proposed
        self._last_resolved = ranked[0][0]
        return ranked[0][0]


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

    @staticmethod
    def _is_no_active_device_error(resp: requests.Response) -> bool:
        if resp.status_code != 404:
            return False
        try:
            err = (resp.json().get("error") or {})
            return err.get("reason") == "NO_ACTIVE_DEVICE"
        except Exception:
            return "NO_ACTIVE_DEVICE" in (resp.text or "")

    def _effective_device_id(self, device_id: Optional[str]) -> Optional[str]:
        if device_id and str(device_id).strip():
            return str(device_id).strip()
        env_id = os.environ.get("SPOTIFY_DEVICE_ID", "").strip()
        return env_id or None

    def get_active_device_id_from_player(self) -> Optional[str]:
        """Device id from ``GET /me/player`` when something is actively playing.

        Spotify sometimes returns an empty ``devices`` list from ``/me/player/devices``
        while ``/me/player`` still includes the current ``device`` (e.g. desktop app).
        """
        resp = requests.get(
            f"{self.API_BASE_URL}/me/player",
            headers=self._headers(),
            timeout=10,
        )
        if resp.status_code == 204:
            return None
        if resp.status_code != 200:
            logger.debug("GET /me/player returned %s", resp.status_code)
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        dev = data.get("device") or {}
        did = dev.get("id")
        if not did or not isinstance(did, str):
            return None
        if dev.get("is_restricted"):
            return None
        return did

    def resolve_playback_device_id(self) -> Optional[str]:
        """Pick a device for ``device_id`` query param: active player, then Connect list."""
        global _spotify_no_device_warn_at
        active = self.get_active_device_id_from_player()
        if active:
            logger.info(
                "Spotify: using device from active playback (GET /me/player), id=%s…",
                active[:16],
            )
            return active

        try:
            data = self.get_devices()
        except Exception as exc:
            logger.warning("Spotify device list request failed: %s", exc)
            return None

        devices: List[Dict[str, Any]] = list(data.get("devices") or [])
        for d in devices:
            if d.get("is_active") and d.get("id") and not d.get("is_restricted"):
                return str(d["id"])
        for d in devices:
            if d.get("id") and not d.get("is_restricted"):
                return str(d["id"])

        if devices:
            logger.warning(
                "Spotify Connect devices exist but none are usable: %s",
                [d.get("name") for d in devices],
            )
        else:
            now = time.time()
            if now - _spotify_no_device_warn_at >= 60.0:
                _spotify_no_device_warn_at = now
                logger.warning(
                    "Spotify: no devices from /me/player/devices and no active /me/player "
                    "(204). Confirm: (1) Spotify **Premium** on the same account as "
                    "SPOTIFY_REFRESH_TOKEN, (2) desktop app logged into that account, "
                    "(3) press Play so something is **currently** playing, (4) re-run "
                    "get_spotify_refresh_token.py if the token is for another user. "
                    "Optional: set SPOTIFY_DEVICE_ID from the Spotify developer console "
                    "or a GET /v1/me/player response while playing."
                )
        return None

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

        Uses ``SPOTIFY_DEVICE_ID`` when ``device_id`` is omitted. If Spotify returns
        ``NO_ACTIVE_DEVICE``, the client retries once using the first available
        Connect device from ``GET /me/player/devices``.

        With shuffle on (default, ``SPOTIFY_SHUFFLE`` unset or truthy), requests a
        random start offset when the Web API exposes a track count; otherwise starts
        at the default first track, then enables API shuffle where supported.
        """
        pinned = self._effective_device_id(device_id)
        params: Dict[str, str] = {}
        if pinned:
            params["device_id"] = pinned

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
        fallback_id: Optional[str] = None
        if (
            resp.status_code not in (200, 204)
            and self._is_no_active_device_error(resp)
            and not pinned
        ):
            fallback_id = self.resolve_playback_device_id()
            if fallback_id:
                resp = requests.put(
                    f"{self.API_BASE_URL}/me/player/play",
                    params={"device_id": fallback_id},
                    json=body,
                    headers=self._headers(),
                    timeout=10,
                )
                if resp.status_code in (200, 204):
                    logger.info(
                        "Spotify playback started on Connect device id=%s…",
                        fallback_id[:16],
                    )

        if resp.status_code not in (200, 204):
            raise RuntimeError(
                f"Spotify playback request failed: {resp.status_code} {resp.text}"
            )

        shuffle_dev = fallback_id or pinned
        if use_shuffle:
            self.set_shuffle(True, device_id=shuffle_dev)

    def get_recommendations(
        self,
        *,
        seed_genres: List[str],
        limit: int = 20,
        market: Optional[str] = None,
        target_energy: Optional[float] = None,
        target_valence: Optional[float] = None,
        target_tempo: Optional[float] = None,
    ) -> List[str]:
        """Return ``spotify:track:`` URIs from ``GET /recommendations``.

        At most **five** seed genres are sent (Spotify limit across all seed types).
        """
        if not seed_genres:
            return []
        base: Dict[str, Any] = {
            "seed_genres": ",".join(seed_genres[:5]),
            "limit": min(max(limit, 1), 100),
        }
        mkt = (market or os.environ.get("SPOTIFY_MARKET", "") or "").strip()
        if mkt:
            base["market"] = mkt

        full = dict(base)
        if target_energy is not None:
            full["target_energy"] = target_energy
        if target_valence is not None:
            full["target_valence"] = target_valence
        if target_tempo is not None:
            full["target_tempo"] = target_tempo

        resp = requests.get(
            f"{self.API_BASE_URL}/recommendations",
            params=full,
            headers=self._headers(),
            timeout=15,
        )
        # Spotify sometimes returns 404 when targets + seeds have no catalog match; retry seeds only.
        if resp.status_code != 200 and len(full) > len(base):
            logger.info(
                "Spotify recommendations status=%s; retrying without target_energy/valence/tempo.",
                resp.status_code,
            )
            resp = requests.get(
                f"{self.API_BASE_URL}/recommendations",
                params=base,
                headers=self._headers(),
                timeout=15,
            )

        if resp.status_code != 200:
            _throttled_recommendations_hint(resp.status_code, resp.text or "", full)
            raise RuntimeError(
                f"Spotify recommendations failed: {resp.status_code} {(resp.text or '').strip() or '(no body)'}"
            )
        tracks = resp.json().get("tracks") or []
        out: List[str] = []
        for t in tracks:
            uri = (t or {}).get("uri")
            if uri and isinstance(uri, str) and uri.startswith("spotify:track:"):
                out.append(uri)
        return out

    def play_track_uris(
        self,
        uris: List[str],
        device_id: Optional[str] = None,
    ) -> None:
        """Start playback of explicit tracks (no playlist/album context)."""
        if not uris:
            raise ValueError("play_track_uris requires at least one URI")
        pinned = self._effective_device_id(device_id)
        params: Dict[str, str] = {}
        if pinned:
            params["device_id"] = pinned
        body: Dict[str, Any] = {"uris": uris}
        resp = requests.put(
            f"{self.API_BASE_URL}/me/player/play",
            params=params,
            json=body,
            headers=self._headers(),
            timeout=10,
        )
        fallback_id: Optional[str] = None
        if (
            resp.status_code not in (200, 204)
            and self._is_no_active_device_error(resp)
            and not pinned
        ):
            fallback_id = self.resolve_playback_device_id()
            if fallback_id:
                resp = requests.put(
                    f"{self.API_BASE_URL}/me/player/play",
                    params={"device_id": fallback_id},
                    json=body,
                    headers=self._headers(),
                    timeout=10,
                )
                if resp.status_code in (200, 204):
                    logger.info(
                        "Spotify playback started on Connect device id=%s…",
                        fallback_id[:16],
                    )

        if resp.status_code not in (200, 204):
            raise RuntimeError(
                f"Spotify playback request failed: {resp.status_code} {resp.text}"
            )


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
        # Minimum seconds between playlist changes (default 10s; SPOTIFY_MIN_SWITCH_S=0 to disable).
        self._min_switch_s: float = float(os.environ.get("SPOTIFY_MIN_SWITCH_S", "10") or "10")
        mode = os.environ.get("SPOTIFY_MOOD_CONTEXT_MODE", "random").strip().lower()
        if mode not in ("random", "round_robin", "first"):
            mode = "random"
        self._context_pick_mode = mode
        self._round_robin_index: dict[str, int] = defaultdict(int)

    def _pick_context_uri(self, mood: str) -> Optional[str]:
        choices = resolve_playlist_choices(mood, self._mood_playlists)
        if not choices:
            return None
        if len(choices) == 1 or self._context_pick_mode == "first":
            return choices[0]
        if self._context_pick_mode == "round_robin":
            i = self._round_robin_index[mood] % len(choices)
            self._round_robin_index[mood] += 1
            return choices[i]
        return random.choice(choices)

    def update(
        self,
        features: NeuroFeatures,
        device_id: Optional[str] = None,
        *,
        stable_mood: Optional[str] = None,
    ) -> None:
        """Update Spotify playback based on the latest features.

        Pass ``stable_mood`` when using :class:`MoodStabilizer` (EMA + vote) in
        ``main.py``; otherwise mood is inferred with :func:`propose_mood`.
        """
        mood = stable_mood if stable_mood is not None else classify_mood(features)

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


class SpotifyNeuroRecommendationController:
    """Drive playback with **one recommended track** per mood change.

    Uses ``GET /v1/recommendations`` with ``target_energy``, ``target_valence``,
    and ``target_tempo`` derived from :class:`NeuroFeatures`. Seed genres narrow
    the catalog (Spotify requires at least one seed).
    """

    def __init__(
        self,
        spotify_client: SpotifyClient,
        seed_genres: List[str],
    ) -> None:
        self._spotify = spotify_client
        self._seed_genres = [g.strip().lower() for g in seed_genres if g.strip()][:5]
        self._current_mood: Optional[str] = None
        self._last_switch_at: float = 0.0
        self._min_switch_s: float = float(os.environ.get("SPOTIFY_MIN_SWITCH_S", "10") or "10")
        try:
            self._rec_limit = int(os.environ.get("SPOTIFY_RECOMMENDATIONS_LIMIT", "20") or "20")
        except ValueError:
            self._rec_limit = 20

    def update(
        self,
        features: NeuroFeatures,
        device_id: Optional[str] = None,
        *,
        stable_mood: Optional[str] = None,
    ) -> None:
        mood = stable_mood if stable_mood is not None else classify_mood(features)

        if mood == self._current_mood:
            return

        now = time.time()
        if self._last_switch_at and (now - self._last_switch_at) < self._min_switch_s:
            return

        if not self._seed_genres:
            return

        targets = neuro_features_to_recommendation_targets(features)
        try:
            uris = self._spotify.get_recommendations(
                seed_genres=self._seed_genres,
                limit=max(1, min(self._rec_limit, 100)),
                target_energy=targets["target_energy"],
                target_valence=targets["target_valence"],
                target_tempo=targets["target_tempo"],
            )
        except Exception as exc:
            # Details + throttled hints are logged from get_recommendations().
            logger.debug("Spotify recommendations request failed: %s", exc)
            return

        if not uris:
            logger.warning(
                "Spotify recommendations returned no tracks (check SPOTIFY_SEED_GENRES)."
            )
            return

        pick = random.choice(uris)
        try:
            self._spotify.play_track_uris([pick], device_id=device_id)
        except Exception as exc:
            logger.warning("Spotify track playback failed: %s", exc)
            return

        logger.info(
            "Spotify recommendation track=%s targets energy=%.2f valence=%.2f tempo=%.0f mood=%s",
            pick,
            targets["target_energy"],
            targets["target_valence"],
            targets["target_tempo"],
            mood,
        )
        self._current_mood = mood
        self._last_switch_at = now

