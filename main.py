from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load before src.constants so SIMULATE / EEG_SIM (and Spotify vars) apply to local runs.
load_dotenv(Path(__file__).resolve().parent / ".env")

import logging
import os
import time
from collections import deque
from typing import TYPE_CHECKING

import numpy as np
from scipy.signal import butter, lfilter, iirnotch

from src.processing.fifo import MirrorCircleFIFO
import src.constants as const
from src.music_gen.spotify_controller import (
    NeuroFeatures as SpotifyNeuroFeatures,
    SpotifyClient,
    SpotifyNeuroController,
    classify_mood,
)
from src.music_gen.spotify_mapping_store import resolve_mood_playlists

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


# ── Feature → Spotify mapping ─────────────────────────────────────────────────

energy_history: deque[float] = deque(maxlen=50)


def features_to_spotify(eeg_features: dict) -> SpotifyNeuroFeatures:
    alpha_sup_mean = float(np.mean(eeg_features["alpha_suppression"]))
    energy_raw = float(np.clip(alpha_sup_mean, -50.0, 100.0))
    energy_history.append(energy_raw)
    e_min = min(energy_history)
    e_max = max(energy_history)
    if (e_max - e_min) < 1e-9:
        energy = 0.5
    else:
        energy = float(np.clip((energy_raw - e_min) / (e_max - e_min), 0.0, 1.0))

    tb_mean = float(np.mean(eeg_features["theta_beta_ratio"]))
    focus = float(np.clip((3.0 - tb_mean) / 2.5, 0.0, 1.0))

    return SpotifyNeuroFeatures(energy=energy, focus=focus)


# ── Simulated EEG signal (raw signal only, features are computed normally) ────

def generate_sim_chunk() -> np.ndarray:
    """Generate one window of simulated raw EEG signal (no feature simulation)."""
    t = np.arange(const.WINDOW_SIZE, dtype=np.float32) / float(const.SAMPLE_RATE)
    signal_1d = (
        0.5 * np.sin(2 * np.pi * 10.0 * t)
        + 0.3 * np.sin(2 * np.pi * 20.0 * t)
        + np.random.normal(scale=0.2, size=const.WINDOW_SIZE)
    ).astype(np.float32)
    return np.tile(signal_1d[:, None], (1, const.N_CHANNELS))


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
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

    # ── Spotify controller (optional) ─────────────────────────────────────
    spotify_controller: SpotifyNeuroController | None = None
    refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()
    if refresh_token:
        mood_playlists = resolve_mood_playlists()
        if mood_playlists:
            spotify_controller = SpotifyNeuroController(
                SpotifyClient(
                    client_id=const.SPOTIFY_CLIENT_ID,
                    client_secret=const.SPOTIFY_CLIENT_SECRET,
                    refresh_token=refresh_token,
                ),
                mood_playlists,
            )
            logger.info("Spotify neuro controller enabled.")
        else:
            logger.warning(
                "Spotify token set but no mood playlists configured — Spotify disabled."
            )
    else:
        logger.info("No SPOTIFY_REFRESH_TOKEN — Spotify disabled.")

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
        spotify_features = features_to_spotify(eeg_features)
        mood = classify_mood(spotify_features)

        logger.info(
            "Theta/Beta=%.2f | Alpha Sup=%.1f%% | energy=%.2f focus=%.2f | mood=%s",
            float(np.mean(eeg_features["theta_beta_ratio"])),
            float(np.mean(eeg_features["alpha_suppression"])),
            spotify_features.energy,
            spotify_features.focus,
            mood,
        )

        if spotify_controller is not None:
            try:
                spotify_controller.update(spotify_features)
            except Exception as exc:
                logger.warning("Spotify update failed: %s", exc)
