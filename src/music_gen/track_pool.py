"""Labeled Spotify track pool for EEG-matched playback from a local CSV.

Loads a CSV with at least ``track_id``, ``energy``, ``valence``, ``tempo`` (as in
TidyTuesday ``spotify_songs.csv``). Builds normalized feature vectors for fast
nearest-neighbor selection.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def _f(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class TrackPool:
    """Immutable pool of ``spotify:track:`` URIs with features in [0,1]³ (e, v, tempo_norm)."""

    uris: np.ndarray  # object array of str
    mat: np.ndarray  # (n, 3) float64 — energy, valence, tempo normalized

    @property
    def size(self) -> int:
        return int(self.uris.shape[0])

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        *,
        tempo_norm_lo: float | None = None,
        tempo_norm_hi: float | None = None,
    ) -> TrackPool:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            logger.warning("Track pool CSV not found: %s", p)
            return cls(np.array([], dtype=object), np.zeros((0, 3), dtype=np.float64))

        t_lo = float(
            tempo_norm_lo
            if tempo_norm_lo is not None
            else os.environ.get("SPOTIFY_POOL_TEMPO_MIN", "60") or "60"
        )
        t_hi = float(
            tempo_norm_hi
            if tempo_norm_hi is not None
            else os.environ.get("SPOTIFY_POOL_TEMPO_MAX", "200") or "200"
        )
        if t_hi <= t_lo:
            t_hi = t_lo + 1.0

        seen: set[str] = set()
        rows_uri: list[str] = []
        rows_e: list[float] = []
        rows_v: list[float] = []
        rows_tempo: list[float] = []

        with p.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                logger.warning("Track pool CSV has no header: %s", p)
                return cls(np.array([], dtype=object), np.zeros((0, 3), dtype=np.float64))
            fields = {h.strip().lower(): h for h in reader.fieldnames}

            def col(*names: str) -> str | None:
                for n in names:
                    if n.lower() in fields:
                        return fields[n.lower()]
                return None

            c_id = col("track_id", "id", "spotify_id")
            c_e = col("energy")
            c_v = col("valence")
            c_t = col("tempo", "bpm")
            if not (c_id and c_e and c_v and c_t):
                logger.warning(
                    "Track pool CSV needs columns track_id, energy, valence, tempo — got %s",
                    reader.fieldnames,
                )
                return cls(np.array([], dtype=object), np.zeros((0, 3), dtype=np.float64))

            for raw in reader:
                tid = (raw.get(c_id) or "").strip()
                if not tid:
                    continue
                e = _f(raw.get(c_e, ""))
                v = _f(raw.get(c_v, ""))
                t = _f(raw.get(c_t, ""))
                if e is None or v is None or t is None:
                    continue
                if tid in seen:
                    continue
                seen.add(tid)
                rows_uri.append(f"spotify:track:{tid}")
                rows_e.append(float(np.clip(e, 0.0, 1.0)))
                rows_v.append(float(np.clip(v, 0.0, 1.0)))
                rows_tempo.append(float(t))

        if not rows_uri:
            logger.warning("Track pool CSV yielded no valid rows: %s", p)
            return cls(np.array([], dtype=object), np.zeros((0, 3), dtype=np.float64))

        tempos = np.asarray(rows_tempo, dtype=np.float64)
        t_norm = (np.clip(tempos, t_lo, t_hi) - t_lo) / (t_hi - t_lo)

        mat = np.column_stack(
            [
                np.asarray(rows_e, dtype=np.float64),
                np.asarray(rows_v, dtype=np.float64),
                t_norm.astype(np.float64),
            ]
        )
        uris = np.asarray(rows_uri, dtype=object)
        logger.info(
            "Track pool loaded: %d unique tracks from %s (tempo norm %.0f–%.0f BPM)",
            len(rows_uri),
            p.name,
            t_lo,
            t_hi,
        )
        return cls(uris=uris, mat=mat)

    def pick_nearest(
        self,
        target_energy: float,
        target_valence: float,
        target_tempo_bpm: float,
        *,
        rng: np.random.Generator,
        exclude: set[str],
        top_k: int,
        weights: tuple[float, float, float],
    ) -> str | None:
        if self.size == 0:
            return None

        t_lo = float(os.environ.get("SPOTIFY_POOL_TEMPO_MIN", "60") or "60")
        t_hi = float(os.environ.get("SPOTIFY_POOL_TEMPO_MAX", "200") or "200")
        if t_hi <= t_lo:
            t_hi = t_lo + 1.0
        t_n = float((np.clip(target_tempo_bpm, t_lo, t_hi) - t_lo) / (t_hi - t_lo))

        e = float(np.clip(target_energy, 0.0, 1.0))
        v = float(np.clip(target_valence, 0.0, 1.0))
        w_e, w_v, w_t = weights

        diff = self.mat - np.array([e, v, t_n], dtype=np.float64)
        d = w_e * diff[:, 0] ** 2 + w_v * diff[:, 1] ** 2 + w_t * diff[:, 2] ** 2

        order = np.argsort(d)
        k = max(1, min(top_k, self.size))
        candidates: list[int] = []
        for idx in order:
            u = str(self.uris[int(idx)])
            if u in exclude:
                continue
            candidates.append(int(idx))
            if len(candidates) >= k:
                break

        if not candidates:
            for idx in order:
                candidates.append(int(idx))
                if len(candidates) >= k:
                    break

        pick = int(rng.choice(candidates))
        return str(self.uris[pick])
