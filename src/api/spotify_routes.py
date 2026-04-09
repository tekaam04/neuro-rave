from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
import urllib.parse
from typing import Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from src.music_gen.bootstrap_spotify_playback import try_start_calm_context_playback
from src.music_gen.dashboard_playback_mode import (
    read_dashboard_playback_mode,
    write_dashboard_playback_mode,
)
from src.music_gen.spotify_mapping_store import (
    load_mood_playlists,
    parse_spotify_context_input,
    save_mood_playlists,
)
from src.music_gen.spotify_refresh_token import (
    load_spotify_refresh_token,
    save_spotify_refresh_token_to_file,
)

router = APIRouter(prefix="/spotify", tags=["spotify"])
logger = logging.getLogger(__name__)

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE_URL = "https://api.spotify.com/v1"


def _spotify_error_summary(resp: requests.Response) -> str:
    """Compact, user-safe summary for Spotify API/token failures."""
    try:
        data = resp.json()
    except Exception:
        txt = (resp.text or "").strip()
        return txt[:220] if txt else f"HTTP {resp.status_code}"

    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or "").strip()
            status = err.get("status")
            reason = str(err.get("reason") or "").strip()
            out = f"{status or resp.status_code} {msg}".strip()
            if reason:
                out = f"{out} (reason={reason})"
            return out
        desc = str(data.get("error_description") or "").strip()
        if desc:
            return desc
        if err:
            return str(err)
    return str(data)[:220]


def _resolved_spotify_app_credentials() -> tuple[str, str]:
    """Match ``main.py``: optional ``SPOTIFY_*`` env vars override ``config/constants.json``."""
    cid = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    sec = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if cid and sec:
        return cid, sec
    try:
        from src.constants import SPOTIFY_CLIENT_ID as cj
        from src.constants import SPOTIFY_CLIENT_SECRET as cs

        return str(cj or "").strip(), str(cs or "").strip()
    except Exception:
        return "", ""

OAUTH_SCOPES = [
    "user-modify-playback-state",
    "user-read-playback-state",
    "playlist-read-private",
    "playlist-read-collaborative",
]

# state -> (expiry_unix, pkce_code_verifier)
_oauth_states: Dict[str, tuple[float, str]] = {}


def _pkce_verifier_and_challenge() -> tuple[str, str]:
    """RFC 7636 S256: verifier 43–128 chars; challenge = BASE64URL(SHA256(verifier)) without padding."""
    verifier = secrets.token_urlsafe(48)
    while len(verifier) < 43:
        verifier += secrets.token_urlsafe(8)
    verifier = verifier[:128]
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _prune_oauth_states() -> None:
    now = time.time()
    for s, (exp, _) in list(_oauth_states.items()):
        if exp < now:
            del _oauth_states[s]


def _oauth_callback_url() -> str:
    explicit = os.environ.get("SPOTIFY_OAUTH_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    from src.constants import WS_PORT

    # Spotify (since Apr 2025) rejects ``http://localhost`` redirect URIs; HTTP is only allowed
    # for explicit loopback literals, e.g. ``http://127.0.0.1:PORT`` (see Spotify redirect URI docs).
    host = os.environ.get("SPOTIFY_OAUTH_PUBLIC_HOST", "127.0.0.1").strip() or "127.0.0.1"
    return f"http://{host}:{WS_PORT}/spotify/oauth/callback"


def _oauth_success_redirect() -> str:
    return (
        os.environ.get("SPOTIFY_OAUTH_SUCCESS_URL", "http://localhost:5173/setup?spotify=connected").strip()
        or "http://localhost:5173/setup?spotify=connected"
    )


class SpotifyUserContext(BaseModel):
    user_id: str
    client_id: str
    client_secret: str
    refresh_token: str


def get_spotify_user_context() -> SpotifyUserContext:
    client_id, client_secret = _resolved_spotify_app_credentials()
    refresh = load_spotify_refresh_token()
    if not client_id or not client_secret or not refresh:
        raise HTTPException(
            status_code=503,
            detail=(
                "Spotify not configured: set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET "
                "(environment or config/constants.json), and connect your account (Setup page) "
                "or set SPOTIFY_REFRESH_TOKEN / config/.spotify_refresh_token"
            ),
        )
    user_id = os.environ.get("SPOTIFY_USER_ID", "default").strip() or "default"
    return SpotifyUserContext(
        user_id=user_id,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh,
    )


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        headers={"Authorization": f"Basic {auth_header}"},
        timeout=10,
    )
    if resp.status_code != 200:
        detail = _spotify_error_summary(resp)
        logger.warning("Spotify token refresh failed (%s): %s", resp.status_code, detail)
        raise HTTPException(status_code=resp.status_code, detail=f"Token refresh failed: {detail}")
    data = resp.json()
    rotated = str(data.get("refresh_token") or "").strip()
    if rotated and rotated != refresh_token:
        # Spotify may rotate refresh tokens; persist immediately for local runs.
        save_spotify_refresh_token_to_file(rotated)
        logger.info("Spotify refresh token rotated and saved locally.")
    token = data.get("access_token")
    if not token:
        raise HTTPException(status_code=500, detail="Spotify token response missing access_token")
    return str(token)


def spotify_get_playlists(access_token: str) -> List[dict]:
    playlists: List[dict] = []
    url: Optional[str] = f"{API_BASE_URL}/me/playlists"
    headers = {"Authorization": f"Bearer {access_token}"}

    while url:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            detail = _spotify_error_summary(resp)
            logger.warning("Spotify playlists fetch failed (%s): %s", resp.status_code, detail)
            raise HTTPException(status_code=resp.status_code, detail=f"Spotify playlists failed: {detail}")
        data = resp.json()
        for item in data.get("items", []) or []:
            if isinstance(item, dict):
                playlists.append(item)
        url = data.get("next")

    return playlists


def _context_title(access_token: str, uri: str) -> str:
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        if uri.startswith("spotify:album:"):
            aid = uri.split(":")[-1]
            r = requests.get(
                f"{API_BASE_URL}/albums/{aid}",
                headers=headers,
                params={"fields": "name"},
                timeout=10,
            )
        elif uri.startswith("spotify:playlist:"):
            pid = uri.split(":")[-1]
            r = requests.get(
                f"{API_BASE_URL}/playlists/{pid}",
                headers=headers,
                params={"fields": "name"},
                timeout=10,
            )
        else:
            return uri
        if r.status_code != 200:
            return uri
        data = r.json()
        return str(data.get("name") or uri)
    except Exception:
        return uri


MOOD_KEYWORDS: Dict[str, List[str]] = {
    "calm": ["calm", "chill", "ambient", "sleep", "relax", "lofi", "downtempo"],
    "focus": ["focus", "study", "deep work", "concentration", "instrumental", "coding"],
    "hype": ["hype", "workout", "gym", "party", "edm", "techno", "run", "energy"],
}


def score_playlist_for_mood(name: str, description: str, mood: str) -> int:
    text = f"{name} {description}".lower()
    return sum(1 for kw in MOOD_KEYWORDS[mood] if kw in text)


def suggest_mood_playlists(playlists: List[dict]) -> Dict[str, Optional[dict]]:
    scored: Dict[str, List[dict]] = {mood: [] for mood in MOOD_KEYWORDS}

    for p in playlists:
        name = str(p.get("name", ""))
        desc = str(p.get("description", "") or "")
        uri = p.get("uri")
        if not uri or not isinstance(uri, str):
            continue
        for mood in MOOD_KEYWORDS:
            s = score_playlist_for_mood(name, desc, mood)
            if s > 0:
                scored[mood].append({"score": s, "uri": uri, "name": name})

    result: Dict[str, Optional[dict]] = {}
    used: set[str] = set()

    for mood in ("calm", "focus", "hype"):
        ranked = sorted(scored[mood], key=lambda x: x["score"], reverse=True)
        choice = next((r for r in ranked if r["uri"] not in used), None)
        result[mood] = choice
        if choice:
            used.add(choice["uri"])

    return result


class PlaylistOption(BaseModel):
    uri: str
    name: str


class SuggestionsResponse(BaseModel):
    suggestions: Dict[str, Optional[dict]]
    candidates: List[PlaylistOption]


class MoodMappingIn(BaseModel):
    calm_uri: str | List[str]
    focus_uri: str | List[str]
    hype_uri: str | List[str]
    deep_focus_uri: Optional[str | List[str]] = None

    @staticmethod
    def _coerce_uri_list(v: object, *, required: bool) -> List[str]:
        if v is None:
            return [] if not required else []
        raw_parts: List[str] = []
        if isinstance(v, str):
            # Accept single URI/URL, comma-separated, or newline-separated lists.
            raw_parts = [p.strip() for p in v.replace("\r\n", "\n").replace(",", "\n").split("\n")]
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    raw_parts.extend(
                        [p.strip() for p in item.replace("\r\n", "\n").replace(",", "\n").split("\n")]
                    )
                else:
                    raise ValueError("URI list entries must be strings")
        else:
            raise ValueError("URI/link input must be a string or list of strings")
        out: List[str] = []
        seen: set[str] = set()
        for part in raw_parts:
            if not part:
                continue
            uri = parse_spotify_context_input(part)
            if not uri:
                raise ValueError(
                    "Use spotify:playlist:… / spotify:album:… or open.spotify.com playlist/album URLs"
                )
            if uri not in seen:
                out.append(uri)
                seen.add(uri)
        if required and not out:
            raise ValueError("At least one URI/link is required")
        return out

    @field_validator("calm_uri", "focus_uri", "hype_uri", mode="before")
    @classmethod
    def coerce_required_uris(cls, v: object) -> List[str]:
        return cls._coerce_uri_list(v, required=True)

    @field_validator("deep_focus_uri", mode="before")
    @classmethod
    def coerce_deep(cls, v: object) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        out = cls._coerce_uri_list(v, required=False)
        return out if out else None


class MoodMappingOut(BaseModel):
    user_id: str
    calm_uri: str
    focus_uri: str
    hype_uri: str
    calm_uris: List[str]
    focus_uris: List[str]
    hype_uris: List[str]
    deep_focus_uri: Optional[str] = None
    deep_focus_uris: List[str] = Field(default_factory=list)
    updated_at: float
    bootstrap_playback_ok: bool = False
    bootstrap_playback_error: Optional[str] = None


class DashboardPlaybackModeIn(BaseModel):
    mode: str = Field(..., min_length=2)

    @field_validator("mode", mode="before")
    @classmethod
    def _norm_playlist_pool(cls, v: object) -> str:
        s = str(v).strip().lower()
        if s in ("playlist", "context"):
            return "context"
        if s == "pool":
            return "pool"
        raise ValueError("mode must be playlist or pool")


class DashboardPlaybackModeOut(BaseModel):
    """``playlist`` means context (mood playlists); ``pool`` means CSV track pool."""

    mode: str


class MoodSlotDisplay(BaseModel):
    uri: str
    name: str


class MoodMappingDisplayOut(BaseModel):
    calm: MoodSlotDisplay
    focus: MoodSlotDisplay
    hype: MoodSlotDisplay
    deep_focus: Optional[MoodSlotDisplay] = None


class SetupStatusOut(BaseModel):
    client_configured: bool
    refresh_token_configured: bool
    mood_mapping_saved: bool
    oauth_authorize_path: str
    # Byte-for-byte match required in Spotify app settings (authorize request redirect_uri).
    oauth_redirect_uri: str


def _api_mode_label(stored: str) -> str:
    return "playlist" if stored == "context" else stored


@router.get("/dashboard/playback-mode", response_model=DashboardPlaybackModeOut)
def get_dashboard_playback_mode_http() -> DashboardPlaybackModeOut:
    raw = read_dashboard_playback_mode()
    if raw == "context":
        label = "playlist"
    elif raw == "pool":
        label = "pool"
    else:
        label = "playlist"
    return DashboardPlaybackModeOut(mode=label)


@router.post("/dashboard/playback-mode", response_model=DashboardPlaybackModeOut)
def post_dashboard_playback_mode_http(
    body: DashboardPlaybackModeIn,
) -> DashboardPlaybackModeOut:
    stored = write_dashboard_playback_mode(body.mode)
    return DashboardPlaybackModeOut(mode=_api_mode_label(stored))


@router.get("/setup/status", response_model=SetupStatusOut)
def setup_status() -> SetupStatusOut:
    rid = load_spotify_refresh_token()
    cid, csec = _resolved_spotify_app_credentials()
    has_map = load_mood_playlists() is not None
    return SetupStatusOut(
        client_configured=bool(cid and csec),
        refresh_token_configured=bool(rid),
        mood_mapping_saved=has_map,
        oauth_authorize_path="/spotify/oauth/authorize",
        oauth_redirect_uri=_oauth_callback_url(),
    )


@router.get("/oauth/authorize")
def oauth_authorize() -> RedirectResponse:
    client_id, client_secret = _resolved_spotify_app_credentials()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail=(
                "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set via environment "
                "or config/constants.json"
            ),
        )
    _prune_oauth_states()
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _pkce_verifier_and_challenge()
    _oauth_states[state] = (time.time() + 600.0, code_verifier)
    redirect_uri = _oauth_callback_url()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(OAUTH_SCOPES),
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)


@router.get("/oauth/callback")
def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify authorization error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    entry = _oauth_states.pop(state, None)
    if entry is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state — open the Setup page and click Connect Spotify again.",
        )
    exp, code_verifier = entry
    if exp < time.time():
        raise HTTPException(
            status_code=400,
            detail="OAuth state expired — click Connect Spotify again.",
        )

    client_id, client_secret = _resolved_spotify_app_credentials()
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Spotify app credentials missing")
    redirect_uri = _oauth_callback_url()
    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    # PKCE: code_verifier in body; client auth via Basic (confidential Spotify app).
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {resp.text}")
    data = resp.json()
    refresh = data.get("refresh_token")
    if not refresh:
        raise HTTPException(
            status_code=500,
            detail="Spotify did not return a refresh token — revoke app access in Spotify account settings and try again.",
        )
    save_spotify_refresh_token_to_file(str(refresh))
    return RedirectResponse(_oauth_success_redirect(), status_code=302)


@router.get("/playlists/suggestions", response_model=SuggestionsResponse)
def get_playlist_suggestions(user: SpotifyUserContext = Depends(get_spotify_user_context)) -> SuggestionsResponse:
    access_token = refresh_access_token(user.client_id, user.client_secret, user.refresh_token)
    playlists = spotify_get_playlists(access_token)
    suggestions = suggest_mood_playlists(playlists)
    candidates = [
        PlaylistOption(uri=str(p["uri"]), name=str(p.get("name", "Untitled")))
        for p in playlists
        if p.get("uri")
    ]
    return SuggestionsResponse(suggestions=suggestions, candidates=candidates)


@router.post("/playlists/mapping", response_model=MoodMappingOut)
def save_playlist_mapping(
    payload: MoodMappingIn,
    user: SpotifyUserContext = Depends(get_spotify_user_context),
) -> MoodMappingOut:
    top_uris = {payload.calm_uri[0], payload.focus_uri[0], payload.hype_uri[0]}
    if len(top_uris) < 3:
        raise HTTPException(
            status_code=400,
            detail="calm_uri, focus_uri, and hype_uri must be three different Spotify contexts",
        )

    mapping: Dict[str, str | List[str]] = {
        "calm": payload.calm_uri,
        "focus": payload.focus_uri,
        "hype": payload.hype_uri,
    }
    if payload.deep_focus_uri:
        mapping["deep_focus"] = payload.deep_focus_uri
    try:
        save_mood_playlists(mapping, user_id=user.user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    base = _mapping_to_out(user.user_id)
    ok, err = False, None
    if read_dashboard_playback_mode() == "context":
        ok, err = try_start_calm_context_playback()
    return base.model_copy(
        update={"bootstrap_playback_ok": ok, "bootstrap_playback_error": err},
    )


@router.get("/playlists/mapping", response_model=MoodMappingOut)
def get_playlist_mapping(user: SpotifyUserContext = Depends(get_spotify_user_context)) -> MoodMappingOut:
    m = load_mood_playlists()
    if not m:
        raise HTTPException(status_code=404, detail="No mood mapping saved; use the Setup page or POST /spotify/playlists/mapping")
    return _mood_dict_to_out(user.user_id, m)


@router.get("/playlists/mapping/display", response_model=MoodMappingDisplayOut)
def get_playlist_mapping_display(user: SpotifyUserContext = Depends(get_spotify_user_context)) -> MoodMappingDisplayOut:
    m = load_mood_playlists()
    if not m:
        raise HTTPException(status_code=404, detail="No mood mapping saved")
    access_token = refresh_access_token(user.client_id, user.client_secret, user.refresh_token)
    calm_uri, focus_uri, hype_uri = m["calm"][0], m["focus"][0], m["hype"][0]
    out = MoodMappingDisplayOut(
        calm=MoodSlotDisplay(uri=calm_uri, name=_context_title(access_token, calm_uri)),
        focus=MoodSlotDisplay(uri=focus_uri, name=_context_title(access_token, focus_uri)),
        hype=MoodSlotDisplay(uri=hype_uri, name=_context_title(access_token, hype_uri)),
    )
    if "deep_focus" in m and m["deep_focus"]:
        du = m["deep_focus"][0]
        out.deep_focus = MoodSlotDisplay(uri=du, name=_context_title(access_token, du))
    return out


def _mood_dict_to_out(user_id: str, m: dict[str, List[str]]) -> MoodMappingOut:
    df_uri: Optional[str] = None
    df_uris: List[str] = []
    if "deep_focus" in m and m["deep_focus"]:
        df_uris = list(m["deep_focus"])
        df_uri = df_uris[0] if df_uris else None
    return MoodMappingOut(
        user_id=user_id,
        calm_uri=m["calm"][0],
        focus_uri=m["focus"][0],
        hype_uri=m["hype"][0],
        calm_uris=m["calm"],
        focus_uris=m["focus"],
        hype_uris=m["hype"],
        deep_focus_uri=df_uri,
        deep_focus_uris=df_uris,
        updated_at=time.time(),
        bootstrap_playback_ok=False,
        bootstrap_playback_error=None,
    )


def _mapping_to_out(user_id: str) -> MoodMappingOut:
    m = load_mood_playlists()
    if not m:
        raise HTTPException(status_code=500, detail="Mapping failed to persist")
    return _mood_dict_to_out(user_id, m)
