from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")

import argparse
import logging
import os
import time
from typing import TYPE_CHECKING

import numpy as np
from scipy.signal import butter, lfilter, iirnotch

from src.processing.fifo import MirrorCircleFIFO
import src.constants as const
from src.music_gen.spotify_controller import (
    MoodStabilizer,
    NeuroFeatures as SpotifyNeuroFeatures,
    SpotifyClient,
    SpotifyNeuroController,
    SpotifyNeuroRecommendationController,
    propose_mood,
)
from src.music_gen.spotify_mapping_store import resolve_mood_playlists
from src.music_gen.spotify_pool_controller import SpotifyNeuroPoolController
from src.music_gen.track_pool import TrackPool

if TYPE_CHECKING:
    from src.streaming.lslbridge import LSLConsumer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ── EEG Band definitions ──────────────────────────────────────────────────────

ALPHA = (8, 13)


# ── DSP helpers ───────────────────────────────────────────────────────────────

def bandpass(data, low, high, fs):
    b, a = butter(4, [low / (fs / 2), high / (fs / 2)], btype="band")
    return lfilter(b, a, data, axis=0)


def notch(data, freq, fs, Q=30):
    b, a = iirnotch(freq / (fs / 2), Q)
    return lfilter(b, a, data, axis=0)


def bandpower(data):
    return np.mean(data ** 2, axis=0)


# ── EEG Processor ─────────────────────────────────────────────────────────────

class EEGProcessor:
    # Attention thresholds
    ALPHA_SUP_THRESHOLD = 0.5   
    SUSTAINED_SEC       = 10.0  
    VARIABILITY_SEC     = 60.0  
    VARIABILITY_MAX     = 0.25  

    def __init__(self, window_seconds: float = 1.0):
        self.window_seconds = window_seconds
        self.buffer = MirrorCircleFIFO.from_seconds(
            seconds=window_seconds,
            sample_rate=const.SAMPLE_RATE,
            n_channels=const.N_CHANNELS,
        )
        self.alpha_hist: list[np.ndarray] = []

        # Sustained attention state
        self._current_streak_sec: float = 0.0

        # Rolling variability state
        self._variability_window_size: int = max(
            1, round(self.VARIABILITY_SEC / window_seconds)
        )
        self._alpha_sup_history: list[float] = []

    # ── internal helpers ──────────────────────────────────────────────────────

    def _update_sustained_streak(self, alpha_sup_mean: float) -> float:
        """Increment or strictly reset the streak; return current length in seconds."""
        if alpha_sup_mean > self.ALPHA_SUP_THRESHOLD:
            self._current_streak_sec += self.window_seconds
        else:
            self._current_streak_sec = 0.0
        return self._current_streak_sec

    def _update_rolling_variability(self, alpha_sup_mean: float) -> float | None:
        """Append value, maintain capped history; return std dev or None if < 60 s."""
        self._alpha_sup_history.append(alpha_sup_mean)
        if len(self._alpha_sup_history) > self._variability_window_size:
            self._alpha_sup_history.pop(0)
        if len(self._alpha_sup_history) < self._variability_window_size:
            return None
        return float(np.std(self._alpha_sup_history))

    # ── main per-window method ────────────────────────────────────────────────

    def process_window(self) -> dict:
        data = self.buffer.data

        # Preprocessing
        data = notch(data, 60, const.SAMPLE_RATE)
        data = bandpass(data, 1, 100, const.SAMPLE_RATE)

        # Alpha extraction
        alpha = bandpass(data, ALPHA[0], ALPHA[1], const.SAMPLE_RATE)
        self.alpha_hist.append(alpha.copy())
        alpha_power = bandpower(alpha)

        # Alpha suppression vs. early baseline, output on 0-1 scale.
        # Negative suppression (alpha enhancement) is floored to 0 — it signals
        # the opposite of attention and shouldn't contribute to either feature.
        alpha_sup_raw = np.zeros(const.N_CHANNELS)
        if len(self.alpha_hist) > 5:
            baseline_data = np.concatenate(self.alpha_hist[:5], axis=0)
            baseline = np.mean(baseline_data ** 2, axis=0)
            alpha_sup_raw = np.where(
                baseline > 0,
                (baseline - alpha_power) / baseline,
                0.0,
            )
        alpha_sup = np.clip(alpha_sup_raw, 0.0, 1.0)

        # ── attention features (scalars) ──────────────────────────────────────
        alpha_sup_mean = float(np.mean(alpha_sup))

        # Focus: how long has suppression been sustained
        sustained_streak    = self._update_sustained_streak(alpha_sup_mean)
        sustained_attention_index = min(sustained_streak / self.SUSTAINED_SEC, 1.0)
        is_attentive        = sustained_streak >= self.SUSTAINED_SEC

        # Energy: how much is suppression fluctuating over the last 60 s
        rolling_variability = self._update_rolling_variability(alpha_sup_mean)
        energy_index = (
            min(rolling_variability / self.VARIABILITY_MAX, 1.0)
            if rolling_variability is not None
            else None
        )

        return {
            "alpha_suppression":         alpha_sup,                  
            "alpha_sup_mean":            alpha_sup_mean,              
            "sustained_streak_sec":      sustained_streak,            
            "sustained_attention_index": sustained_attention_index,   
            "is_attentive":              is_attentive,                
            "rolling_variability":       rolling_variability,         
            "energy_index":              energy_index,                
        }


# ── Simulated EEG ─────────────────────────────────────────────────────────────

_sim_clock_t0: float | None = None
_sim_abs_time: float = 0.0
_sim_last_phase: str | None = None


def _sim_phase_name(elapsed: float) -> str:
    plen = max(5.0, float(const.SIM_PHASE_SECONDS))
    cyc = elapsed % (3.0 * plen)
    if cyc < plen:
        return "calm"
    if cyc < 2.0 * plen:
        return "focus"
    return "hype"


def generate_sim_chunk() -> np.ndarray:
    """Rotate calm → focus → hype every SIM_PHASE_SECONDS (wall clock).

    calm  — high alpha power  → low suppression  → low focus, low energy
    focus — moderate alpha    → mid suppression   → building focus, low energy
    hype  — suppressed alpha  → high suppression  → high focus from streak,
                                                    high energy from variability
    """
    global _sim_clock_t0, _sim_abs_time, _sim_last_phase

    if _sim_clock_t0 is None:
        _sim_clock_t0 = time.monotonic()

    elapsed = time.monotonic() - _sim_clock_t0
    phase = _sim_phase_name(elapsed)
    if phase != _sim_last_phase:
        logger.info(
            "SIM phase -> %s (%.0f s per mood, then rotate)",
            phase,
            float(const.SIM_PHASE_SECONDS),
        )
        _sim_last_phase = phase

    fs = float(const.SAMPLE_RATE)
    n  = int(const.WINDOW_SIZE)
    rng = np.random.default_rng()

    t0 = _sim_abs_time
    t_vec = np.arange(n, dtype=np.float64) / fs + t0
    _sim_abs_time += n / fs

    out = np.zeros((n, const.N_CHANNELS), dtype=np.float32)
    for c in range(const.N_CHANNELS):
        t = t_vec * (1.0 + 0.015 * c)
        if phase == "calm":
            sig = (
                1.2 * np.sin(2 * np.pi * 10.0 * t)
                + 0.4 * np.sin(2 * np.pi * 9.0 * t)
            )
        elif phase == "focus":
            sig = (
                0.6 * np.sin(2 * np.pi * 10.0 * t)
                + 0.5 * np.sin(2 * np.pi * 18.0 * t)
            )
        else:
            sig = (
                0.2 * np.sin(2 * np.pi * 10.0 * t)
                + 0.6 * np.sin(2 * np.pi * 24.0 * t)
                + 0.4 * np.sin(2 * np.pi * 32.0 * t)
            )
        sig = sig + rng.standard_normal(n) * 0.11
        out[:, c] = sig.astype(np.float32)
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="NEURO-RAVE — EEG-driven Spotify")
    mx = ap.add_mutually_exclusive_group()
    mx.add_argument(
        "--spotify-playlist",
        action="store_true",
        help="Spotify: mood → playlist/album (context). Overrides SPOTIFY_PLAYBACK_MODE.",
    )
    mx.add_argument(
        "--spotify-recommendations",
        action="store_true",
        help="Spotify: EEG → recommendations API → single track. Requires SPOTIFY_SEED_GENRES.",
    )
    mx.add_argument(
        "--spotify-pool",
        action="store_true",
        help="Spotify: EEG → local CSV track pool (nearest energy/valence/tempo). See SPOTIFY_TRACK_POOL_CSV.",
    )
    args = ap.parse_args()
    if args.spotify_playlist:
        spotify_cli_mode = "context"
    elif args.spotify_recommendations:
        spotify_cli_mode = "recommendations"
    elif args.spotify_pool:
        spotify_cli_mode = "pool"
    else:
        spotify_cli_mode = None

    # ── WebSocket server ──────────────────────────────────────────────────
    try:
        from src.streaming.ws_server import EEGWebSocketServer
        EEGWebSocketServer().start()
    except ImportError as exc:
        logger.warning(
            "EEG WebSocket server not started (install deps: pip install -r requirements.txt): %s", exc,
        )
    except Exception as exc:
        logger.warning("EEG WebSocket server not started: %s", exc)

    # ── EEG source ────────────────────────────────────────────────────────
    consumer: LSLConsumer | None = None

    if const.SIMULATE:
        logger.info(
            "SIMULATE=true — using generated EEG signal (features computed from real DSP pipeline)"
        )
    else:
        from src.streaming.lslbridge import (
            BioSemi24BitDecoder,
            LSLBridge,
            LSLConsumer,
            LSLPublisher,
            TCPSource,
        )
        logger.info(
            "SIMULATE=false — connecting to BioSemi at %s:%d",
            const.BIOSEMI_HOST,
            const.BIOSEMI_PORT,
        )
        tcp = TCPSource(const.BIOSEMI_HOST, const.BIOSEMI_PORT)
        decoder = BioSemi24BitDecoder(const.N_CHANNELS)
        publisher = LSLPublisher(
            "BioSemiEEG", "EEG", const.N_CHANNELS, const.SAMPLE_RATE, "biosemi_tcp_bridge"
        )
        bridge = LSLBridge(tcp, decoder, publisher)
        bridge.start()

        logger.info("Waiting for LSL stream...")
        try:
            consumer = LSLConsumer("EEG")
        except Exception as exc:
            logger.error("Failed to connect to LSL stream: %s", exc)
            raise SystemExit(1)
        logger.info("LSL stream connected.")

    # ── EEG processor ─────────────────────────────────────────────────────
    processor = EEGProcessor(window_seconds=1.0)

    # ── Spotify controller ────────────────────────────────────────────────
    spotify_controller: (
        SpotifyNeuroController
        | SpotifyNeuroRecommendationController
        | SpotifyNeuroPoolController
        | None
    ) = None
    refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()
    if refresh_token:
        if spotify_cli_mode is not None:
            playback_mode = spotify_cli_mode
        else:
            em = os.environ.get("SPOTIFY_PLAYBACK_MODE", "context").strip().lower()
            playback_mode = em if em in ("context", "recommendations", "pool") else "context"
        spotify = SpotifyClient(
            client_id=const.SPOTIFY_CLIENT_ID,
            client_secret=const.SPOTIFY_CLIENT_SECRET,
            refresh_token=refresh_token,
        )
        if playback_mode == "recommendations":
            raw = os.environ.get("SPOTIFY_SEED_GENRES", "").strip()
            genres = [g.strip() for g in raw.split(",") if g.strip()][:5]
            if not genres:
                logger.warning(
                    "Recommendations mode requires SPOTIFY_SEED_GENRES "
                    "(comma-separated Spotify genre seeds, max 5) — Spotify disabled."
                )
            else:
                spotify_controller = SpotifyNeuroRecommendationController(spotify, genres)
                logger.info("Spotify recommendation mode enabled seeds=%s", genres)
        elif playback_mode == "pool":
            csv_path = (
                os.environ.get("SPOTIFY_TRACK_POOL_CSV", "").strip()
                or str(_PROJECT_ROOT / "config" / "track_pool.csv")
            )
            pool = TrackPool.from_csv(csv_path)
            if pool.size == 0:
                logger.warning(
                    "Spotify pool mode: no tracks loaded from %s — "
                    "copy e.g. TidyTuesday spotify_songs.csv to config/track_pool.csv "
                    "or set SPOTIFY_TRACK_POOL_CSV.",
                    csv_path,
                )
            else:
                spotify_controller = SpotifyNeuroPoolController(spotify, pool)
                logger.info(
                    "Spotify track-pool mode enabled (%d tracks, CSV=%s). "
                    "Interval=%.0fs (SPOTIFY_POOL_MIN_INTERVAL_S).",
                    pool.size,
                    csv_path,
                    float(os.environ.get("SPOTIFY_POOL_MIN_INTERVAL_S", "10") or "10"),
                )
        else:
            mood_playlists = resolve_mood_playlists()
            if mood_playlists:
                spotify_controller = SpotifyNeuroController(spotify, mood_playlists)
                logger.info("Spotify playlist/context mode enabled.")
            else:
                logger.warning(
                    "Spotify token set but no mood playlists configured — Spotify disabled."
                )
    else:
        logger.info("No SPOTIFY_REFRESH_TOKEN — Spotify disabled.")

    mood_stabilizer = MoodStabilizer()

    # ── Main loop ─────────────────────────────────────────────────────────

    while True:
        if const.SIMULATE:
            samples = generate_sim_chunk()
            time.sleep(const.WINDOW_SIZE / const.SAMPLE_RATE)
        else:
            assert consumer is not None
            samples, ts = consumer.get_chunk()
            if len(samples) == 0:
                time.sleep(0.01)
                continue

        processor.buffer.add_chunk(np.asarray(samples, dtype=np.float32))

        if not processor.buffer.full:
            continue

        eeg_features = processor.process_window()

        # Map EEG features to Spotify dimensions.
        # energy_index is None for the first 60 s
        raw_focus  = eeg_features["sustained_attention_index"]   
        raw_energy = eeg_features["energy_index"]               
        raw_energy = raw_energy if raw_energy is not None else 0.5

        se, sf, d_e = mood_stabilizer.smooth(raw_energy, raw_focus)
        spotify_features = SpotifyNeuroFeatures(energy=se, focus=sf, d_energy=d_e)
        proposed = propose_mood(spotify_features)
        mood = mood_stabilizer.majority_mood(proposed)

        logger.info(
            "AlphaSup=%.2f | streak=%.1fs attentive=%s | "
            "focus=%.2f energy=%s | e_sm=%.2f f_sm=%.2f d_e=%.3f | mood=%s (prop=%s)",
            eeg_features["alpha_sup_mean"],
            eeg_features["sustained_streak_sec"],
            eeg_features["is_attentive"],
            raw_focus,
            f"{raw_energy:.2f}" if eeg_features["energy_index"] is not None else "warm-up",
            se,
            sf,
            d_e,
            mood,
            proposed,
        )

        if spotify_controller is not None:
            try:
                spotify_controller.update(spotify_features, stable_mood=mood)
            except Exception as exc:
                logger.warning("Spotify update failed: %s", exc)