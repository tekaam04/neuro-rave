from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent

# Load before src.constants so SIMULATE / EEG_SIM (and Spotify vars) apply to local runs.
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
from src.processing.spotify_feature_pipeline import SpotifyFeaturePipeline
from src.music_gen.spotify_controller import (
    MoodStabilizer,
    NeuroFeatures as SpotifyNeuroFeatures,
    SpotifyClient,
    propose_mood,
)
from src.music_gen.dashboard_playback_mode import read_dashboard_playback_mode
from src.music_gen.spotify_mapping_store import mood_mapping_path
from src.music_gen.spotify_playback_factory import build_playback_controller
from src.music_gen.spotify_refresh_token import load_spotify_refresh_token

if TYPE_CHECKING:
    from src.streaming.lslbridge import LSLConsumer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ── EEG Band definitions ─────────────────────────────────────────────────────

THETA = (4, 8)
ALPHA = (8, 13)
BETA = (13, 30)
GAMMA = (30, 100)


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
    def __init__(self, window_seconds=1.0):
        self.buffer = MirrorCircleFIFO.from_seconds(
            seconds=window_seconds,
            sample_rate=const.SAMPLE_RATE,
            n_channels=const.N_CHANNELS,
        )
        self.alpha_hist = []

    def process_window(self):
        data = self.buffer.data

        data = notch(data, 60, const.SAMPLE_RATE)
        data = bandpass(data, 1, 100, const.SAMPLE_RATE)

        theta = bandpass(data, THETA[0], THETA[1], const.SAMPLE_RATE)
        alpha = bandpass(data, ALPHA[0], ALPHA[1], const.SAMPLE_RATE)
        beta = bandpass(data, BETA[0], BETA[1], const.SAMPLE_RATE)
        gamma = bandpass(data, GAMMA[0], GAMMA[1], const.SAMPLE_RATE)

        self.alpha_hist.append(alpha.copy())

        theta_power = bandpower(theta)
        alpha_power = bandpower(alpha)
        beta_power = bandpower(beta)
        gamma_power = bandpower(gamma)

        theta_beta = np.where(beta_power > 0, theta_power / beta_power, 0.0)

        alpha_sup = np.zeros(const.N_CHANNELS)
        if len(self.alpha_hist) > 5:
            baseline_data = np.concatenate(self.alpha_hist[:5], axis=0)
            baseline = np.mean(baseline_data ** 2, axis=0)
            alpha_sup = np.where(
                baseline > 0,
                (baseline - alpha_power) / baseline * 100,
                0.0,
            )

        return {
            "theta": theta_power,
            "alpha": alpha_power,
            "beta": beta_power,
            "gamma": gamma_power,
            "theta_beta_ratio": theta_beta,
            "alpha_suppression": alpha_sup,
        }


# ── Simulated EEG (raw only; DSP + feature maps match real pipeline) ─────────

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
    """Rotate calm → focus → hype every ``SIM_PHASE_SECONDS`` (wall clock).

    Band content is engineered so bandpower / theta-beta land in ranges that
    map to each mood after the real ``EEGProcessor`` pipeline.
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
    n = int(const.WINDOW_SIZE)
    rng = np.random.default_rng()

    t0 = _sim_abs_time
    t_vec = np.arange(n, dtype=np.float64) / fs + t0
    _sim_abs_time += n / fs

    out = np.zeros((n, const.N_CHANNELS), dtype=np.float32)
    for c in range(const.N_CHANNELS):
        t = t_vec * (1.0 + 0.015 * c)
        if phase == "calm":
            # Alpha/theta-heavy, low beta → higher theta/beta, lower “energy” after pipeline
            sig = (
                1.2 * np.sin(2 * np.pi * 10.0 * t)
                + 0.42 * np.sin(2 * np.pi * 6.5 * t)
                + 0.28 * np.sin(2 * np.pi * 4.0 * t)
            )
        elif phase == "focus":
            # Beta-rich with moderate alpha → lower theta/beta, mid energy
            sig = (
                0.52 * np.sin(2 * np.pi * 18.5 * t)
                + 0.48 * np.sin(2 * np.pi * 12.0 * t)
                + 0.22 * np.sin(2 * np.pi * 10.0 * t)
            )
        else:
            # Beta + high-frequency content → high beta/gamma, high energy
            sig = (
                0.48 * np.sin(2 * np.pi * 24.0 * t)
                + 0.42 * np.sin(2 * np.pi * 32.0 * t)
                + 0.38 * np.sin(2 * np.pi * 38.0 * t)
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
        "--spotify-pool",
        action="store_true",
        help="Spotify: EEG → local CSV track pool (nearest energy/valence/tempo). See SPOTIFY_TRACK_POOL_CSV.",
    )
    args = ap.parse_args()
    if args.spotify_playlist:
        spotify_cli_mode = "context"
    elif args.spotify_pool:
        spotify_cli_mode = "pool"
    else:
        spotify_cli_mode = None

    # ── WebSocket server (optional: requires uvicorn, fastapi; pulls LSL for /ws broadcast) ──
    try:
        from src.streaming.ws_server import EEGWebSocketServer

        EEGWebSocketServer().start()
    except ImportError as exc:
        logger.warning(
            "EEG WebSocket server not started (install deps: pip install -r requirements.txt): %s",
            exc,
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

    # ── Spotify (rebuilt when dashboard mode or mapping / pool CSV changes) ─
    refresh_token = load_spotify_refresh_token()
    spotify_client: SpotifyClient | None = None
    if refresh_token:
        spotify_client = SpotifyClient(
            client_id=const.SPOTIFY_CLIENT_ID,
            client_secret=const.SPOTIFY_CLIENT_SECRET,
            refresh_token=refresh_token,
        )
    else:
        logger.info("No SPOTIFY_REFRESH_TOKEN — Spotify disabled.")

    _spotify_rt: dict[str, object] = {
        "client": spotify_client,
        "controller": None,
        "cache_key": None,
        "last_token": refresh_token,
    }

    def _resolved_main_playback_mode() -> str:
        if spotify_cli_mode is not None:
            return spotify_cli_mode
        return read_dashboard_playback_mode()

    def _spotify_rebuild_cache_key() -> tuple:
        mode = _resolved_main_playback_mode()
        if mode == "context":
            mp = mood_mapping_path()
            mt = mp.stat().st_mtime if mp.is_file() else 0.0
            return (mode, mt)
        if mode == "pool":
            csv_path = Path(
                os.environ.get("SPOTIFY_TRACK_POOL_CSV", "").strip()
                or str(_PROJECT_ROOT / "config" / "track_pool.csv")
            )
            mt = csv_path.stat().st_mtime if csv_path.is_file() else 0.0
            return (mode, mt)
        return (mode, 0.0)

    def _rebuild_spotify_if_needed() -> None:
        current_token = load_spotify_refresh_token()
        prev_token = str(_spotify_rt.get("last_token") or "")
        if current_token != prev_token:
            _spotify_rt["last_token"] = current_token
            existing = _spotify_rt.get("client")
            if not current_token:
                _spotify_rt["cache_key"] = None
                _spotify_rt["controller"] = None
                _spotify_rt["client"] = None
                logger.info("Spotify token removed; disabling Spotify.")
            elif isinstance(existing, SpotifyClient):
                # Token rotated while running: update client in-place so controller
                # state (e.g. min-switch timers/current mood) is preserved.
                existing.update_refresh_token(current_token)
                logger.info("Spotify token updated in running client.")
            else:
                _spotify_rt["cache_key"] = None
                _spotify_rt["controller"] = None
                _spotify_rt["client"] = SpotifyClient(
                    client_id=const.SPOTIFY_CLIENT_ID,
                    client_secret=const.SPOTIFY_CLIENT_SECRET,
                    refresh_token=current_token,
                )
                logger.info("Spotify token detected; enabling Spotify without restart.")

        spotify = _spotify_rt.get("client")
        if not isinstance(spotify, SpotifyClient):
            _spotify_rt["controller"] = None
            _spotify_rt["cache_key"] = None
            return
        key = _spotify_rebuild_cache_key()
        prev_key = _spotify_rt["cache_key"]
        prev_ctrl = _spotify_rt["controller"]
        if key == prev_key and prev_ctrl is not None:
            return
        _spotify_rt["cache_key"] = key
        mode = _resolved_main_playback_mode()
        ctrl = build_playback_controller(mode, spotify=spotify, project_root=_PROJECT_ROOT)
        _spotify_rt["controller"] = ctrl
        if ctrl is not None:
            logger.info("Spotify controller active mode=%s key=%s", mode, key)

    mood_stabilizer = MoodStabilizer()
    spotify_feature_pipeline = SpotifyFeaturePipeline()

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
        raw_feat = spotify_feature_pipeline.process(eeg_features)
        se, sf, d_e = mood_stabilizer.smooth(raw_feat.energy, raw_feat.focus)
        spotify_features = SpotifyNeuroFeatures(energy=se, focus=sf, d_energy=d_e)
        proposed = propose_mood(spotify_features)
        mood = mood_stabilizer.majority_mood(proposed)

        logger.info(
            "Theta/Beta=%.2f | Alpha Sup=%.1f%% | e_in=%.2f f_in=%.2f | "
            "e_sm=%.2f f_sm=%.2f d_e=%.3f | mood=%s (prop=%s)",
            float(np.mean(eeg_features["theta_beta_ratio"])),
            float(np.mean(eeg_features["alpha_suppression"])),
            raw_feat.energy,
            raw_feat.focus,
            spotify_features.energy,
            spotify_features.focus,
            d_e,
            mood,
            proposed,
        )

        _rebuild_spotify_if_needed()
        sp_ctrl = _spotify_rt["controller"]
        if sp_ctrl is not None:
            try:
                sp_ctrl.update(spotify_features, stable_mood=mood)
            except Exception as exc:
                logger.warning("Spotify update failed: %s", exc)
