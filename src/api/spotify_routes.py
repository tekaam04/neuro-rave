from __future__ import annotations

import base64
import os
import time
from typing import Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.music_gen.spotify_mapping_store import load_mood_playlists, save_mood_playlists

router = APIRouter(prefix="/spotify", tags=["spotify"])

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE_URL = "https://api.spotify.com/v1"


class SpotifyUserContext(BaseModel):
    user_id: str
    client_id: str
    client_secret: str
    refresh_token: str


def get_spotify_user_context() -> SpotifyUserContext:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    refresh = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh:
        raise HTTPException(
            status_code=503,
            detail="Spotify not configured: set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN",
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
        raise HTTPException(status_code=resp.status_code, detail=f"Token refresh failed: {resp.text}")
    data = resp.json()
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
            raise HTTPException(status_code=resp.status_code, detail=f"Spotify playlists failed: {resp.text}")
        data = resp.json()
        for item in data.get("items", []) or []:
            if isinstance(item, dict):
                playlists.append(item)
        url = data.get("next")

    return playlists


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
    calm_uri: str = Field(..., min_length=20)
    focus_uri: str = Field(..., min_length=20)
    hype_uri: str = Field(..., min_length=20)

    @field_validator("calm_uri", "focus_uri", "hype_uri")
    @classmethod
    def must_be_spotify_play_context_uri(cls, v: str) -> str:
        if not (
            v.startswith("spotify:playlist:")
            or v.startswith("spotify:album:")
        ):
            raise ValueError("must be a spotify:playlist: or spotify:album: URI")
        return v


class MoodMappingOut(BaseModel):
    user_id: str
    calm_uri: str
    focus_uri: str
    hype_uri: str
    calm_uris: List[str]
    focus_uris: List[str]
    hype_uris: List[str]
    updated_at: float


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
    uris = {payload.calm_uri, payload.focus_uri, payload.hype_uri}
    if len(uris) < 3:
        raise HTTPException(
            status_code=400,
            detail="calm_uri, focus_uri, and hype_uri must be three different Spotify URIs",
        )

    mapping = {"calm": payload.calm_uri, "focus": payload.focus_uri, "hype": payload.hype_uri}
    try:
        save_mood_playlists(mapping, user_id=user.user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return MoodMappingOut(
        user_id=user.user_id,
        calm_uri=payload.calm_uri,
        focus_uri=payload.focus_uri,
        hype_uri=payload.hype_uri,
        calm_uris=[payload.calm_uri],
        focus_uris=[payload.focus_uri],
        hype_uris=[payload.hype_uri],
        updated_at=time.time(),
    )


@router.get("/playlists/mapping", response_model=MoodMappingOut)
def get_playlist_mapping(user: SpotifyUserContext = Depends(get_spotify_user_context)) -> MoodMappingOut:
    m = load_mood_playlists()
    if not m:
        raise HTTPException(status_code=404, detail="No mood mapping saved; POST /spotify/playlists/mapping first")
    return MoodMappingOut(
        user_id=user.user_id,
        calm_uri=m["calm"][0],
        focus_uri=m["focus"][0],
        hype_uri=m["hype"][0],
        calm_uris=m["calm"],
        focus_uris=m["focus"],
        hype_uris=m["hype"],
        updated_at=time.time(),
    )
