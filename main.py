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
from src.music_gen.spotify_controller import (
    MoodStabilizer,
    NeuroFeatures as SpotifyNeuroFeatures,
    SpotifyClient,
    propose_mood,
)
from src.music_gen.dashboard_playback_mode import read_dashboard_playback_mode
from src.music_gen.dashboard_playback_pause import (
    read_dashboard_playback_paused,
    write_dashboard_playback_paused,
)
from src.music_gen.spotify_mapping_store import mood_mapping_path
from src.music_gen.spotify_playback_factory import build_playback_controller
from src.music_gen.spotify_refresh_token import load_spotify_refresh_token

if TYPE_CHECKING:
    from src.streaming.lslbridge import LSLConsumer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ── EEG Band definitions ─────────────────────────────────────────────────────

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
    def __init__(self, window_seconds: float = 1.0):
        self.window_seconds = float(window_seconds)
        self.buffer = MirrorCircleFIFO.from_seconds(
            seconds=window_seconds,
            sample_rate=const.SAMPLE_RATE,
            n_channels=const.N_CHANNELS,
        )
        self.alpha_hist: list[np.ndarray] = []

        # Attention state (alpha-suppression sustained streak + rolling variability)
        self._current_streak_sec: float = 0.0
        self._variability_window_size: int = max(
            1, round(float(const.ATTENTION_VARIABILITY_SEC) / self.window_seconds)
        )
        self._alpha_sup_history: list[float] = []

    def _update_sustained_streak(self, alpha_sup_mean: float) -> float:
        if alpha_sup_mean > float(const.ATTENTION_ALPHA_SUP_THRESHOLD):
            self._current_streak_sec += self.window_seconds
        else:
            self._current_streak_sec = 0.0
        return self._current_streak_sec

    def _update_rolling_variability(self, alpha_sup_mean: float) -> float | None:
        self._alpha_sup_history.append(alpha_sup_mean)
        if len(self._alpha_sup_history) > self._variability_window_size:
            self._alpha_sup_history.pop(0)
        if len(self._alpha_sup_history) < self._variability_window_size:
            return None
        return float(np.std(self._alpha_sup_history))

    def process_window(self):
        data = self.buffer.data

        data = notch(data, 60, const.SAMPLE_RATE)
        data = bandpass(data, 1, 100, const.SAMPLE_RATE)

        alpha = bandpass(data, ALPHA[0], ALPHA[1], const.SAMPLE_RATE)

        self.alpha_hist.append(alpha.copy())

        alpha_power = bandpower(alpha)

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

        alpha_sup_mean = float(np.mean(alpha_sup))
        sustained_streak = self._update_sustained_streak(alpha_sup_mean)
        sustained_attention_index = min(
            sustained_streak / float(const.ATTENTION_SUSTAINED_SEC), 1.0
        )
        is_attentive = sustained_streak >= float(const.ATTENTION_SUSTAINED_SEC)
        rolling_variability = self._update_rolling_variability(alpha_sup_mean)
        energy_index: float | None
        if rolling_variability is None:
            energy_index = None
        else:
            energy_index = min(
                rolling_variability / float(const.ATTENTION_VARIABILITY_MAX), 1.0
            )

        return {
            "alpha_suppression": alpha_sup,
            "alpha_sup_mean": alpha_sup_mean,
            "sustained_streak_sec": sustained_streak,
            "sustained_attention_index": sustained_attention_index,
            "is_attentive": is_attentive,
            "rolling_variability": rolling_variability,
            "energy_index": energy_index,
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


def _sim_phase_blend(elapsed: float) -> tuple[str, str | None, float]:
    plen = max(5.0, float(const.SIM_PHASE_SECONDS))
    phases = ("calm", "focus", "hype")
    cycle = elapsed % (3.0 * plen)
    idx = min(int(cycle // plen), 2)
    phase = phases[idx]
    next_phase = phases[(idx + 1) % len(phases)]
    pos = cycle - (idx * plen)
    blend_sec = min(6.0, plen / 4.0)
    if pos < (plen - blend_sec):
        return phase, None, 0.0
    w = np.clip((pos - (plen - blend_sec)) / blend_sec, 0.0, 1.0)
    return phase, next_phase, float(w)


def _sim_phase_signal(phase: str, t: np.ndarray, ch_idx: int) -> np.ndarray:
    phase_offset = 0.35 * ch_idx
    if phase == "calm":
        alpha_env = 1.0 + 0.03 * np.sin(2 * np.pi * 0.05 * t + phase_offset)
        sig = (
            (1.05 * alpha_env) * np.sin(2 * np.pi * 10.0 * t)
            + 0.30 * np.sin(2 * np.pi * 9.0 * t + 0.2)
            + 0.04 * np.sin(2 * np.pi * 18.0 * t + 0.1)
        )
        noise = 0.035
    elif phase == "focus":
        alpha_env = 1.0 + 0.05 * np.sin(2 * np.pi * 0.08 * t + phase_offset)
        sig = (
            (0.72 * alpha_env) * np.sin(2 * np.pi * 10.0 * t)
            + 0.26 * np.sin(2 * np.pi * 18.0 * t + 0.15)
            + 0.06 * np.sin(2 * np.pi * 22.0 * t + 0.3)
        )
        noise = 0.045
    else:
        alpha_env = 0.35 + 0.18 * np.sin(2 * np.pi * 0.32 * t + phase_offset)
        sig = (
            alpha_env * np.sin(2 * np.pi * 10.0 * t)
            + 0.62 * np.sin(2 * np.pi * 24.0 * t + 0.1)
            + 0.40 * np.sin(2 * np.pi * 32.0 * t + 0.25)
        )
        noise = 0.07
    return sig + noise * np.random.default_rng().standard_normal(t.shape[0])


def generate_sim_chunk() -> np.ndarray:
    """Rotate calm → focus → hype every ``SIM_PHASE_SECONDS`` (wall clock).

    calm  -> high alpha power  -> low suppression  -> low focus, low energy
    focus -> moderate alpha    -> sustained focus  -> lower energy than hype
    hype  -> suppressed alpha  -> high suppression -> high focus from streak,
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
    n = int(const.WINDOW_SIZE)

    t0 = _sim_abs_time
    t_vec = np.arange(n, dtype=np.float64) / fs + t0
    _sim_abs_time += n / fs

    phase_a, phase_b, blend = _sim_phase_blend(elapsed)
    out = np.zeros((n, const.N_CHANNELS), dtype=np.float32)
    for c in range(const.N_CHANNELS):
        t = t_vec * (1.0 + 0.015 * c)
        sig_a = _sim_phase_signal(phase_a, t, c)
        if phase_b is None:
            sig = sig_a
        else:
            sig_b = _sim_phase_signal(phase_b, t, c)
            sig = (1.0 - blend) * sig_a + blend * sig_b
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

    # Always boot in live mode: clear any persisted dashboard pause lock from
    # previous runs so neuro-driven playback updates are active immediately.
    try:
        write_dashboard_playback_paused(False)
    except Exception as exc:
        logger.warning("Failed to clear dashboard pause lock at startup: %s", exc)

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

    # ── Main loop ─────────────────────────────────────────────────────────

    _hb_empty_iters = 0
    _hb_fill_iters = 0
    _hb_last_log = time.monotonic()

    while True:
        if const.SIMULATE:
            samples = generate_sim_chunk()
            time.sleep(const.WINDOW_SIZE / const.SAMPLE_RATE)
        else:
            assert consumer is not None
            # Small timeout lets pylsl block briefly instead of spinning and
            # gives the inlet a chance to deliver samples before we bail out.
            samples, ts = consumer.get_chunk(timeout=0.5)
            if len(samples) == 0:
                _hb_empty_iters += 1
                now_hb = time.monotonic()
                if now_hb - _hb_last_log >= 5.0:
                    logger.info(
                        "HEARTBEAT: main loop alive — empty_iters=%d fill_iters=%d buffer.full=%s",
                        _hb_empty_iters,
                        _hb_fill_iters,
                        processor.buffer.full,
                    )
                    _hb_last_log = now_hb
                time.sleep(0.01)
                continue

        processor.buffer.add_chunk(np.asarray(samples, dtype=np.float32))
        _hb_fill_iters += 1

        if not processor.buffer.full:
            now_hb = time.monotonic()
            if now_hb - _hb_last_log >= 5.0:
                logger.info(
                    "HEARTBEAT: filling — samples=%d empty_iters=%d fill_iters=%d",
                    len(samples),
                    _hb_empty_iters,
                    _hb_fill_iters,
                )
                _hb_last_log = now_hb
            continue

        eeg_features = processor.process_window()
        raw_energy = eeg_features.get("energy_index")
        raw_focus = eeg_features.get("sustained_attention_index")
        # During warm-up, rolling variability is not available yet, so use a
        # neutral energy of 0.5.
        raw_energy = float(raw_energy) if raw_energy is not None else 0.5
        raw_focus = float(raw_focus) if raw_focus is not None else 0.0

        se, sf, d_e = mood_stabilizer.smooth(raw_energy, raw_focus)
        spotify_features = SpotifyNeuroFeatures(energy=se, focus=sf, d_energy=d_e)
        proposed = propose_mood(spotify_features)
        mood = mood_stabilizer.majority_mood(proposed)

        e_idx = eeg_features.get("energy_index")
        logger.info(
            "e_idx=%s | e_in=%.2f f_in=%.2f | "
            "e_sm=%.2f f_sm=%.2f d_e=%.3f | mood=%s (prop=%s)",
            f"{float(e_idx):.2f}" if e_idx is not None else "warm-up",
            raw_energy,
            raw_focus,
            spotify_features.energy,
            spotify_features.focus,
            d_e,
            mood,
            proposed,
        )

        _rebuild_spotify_if_needed()
        sp_ctrl = _spotify_rt["controller"]
        if sp_ctrl is not None:
            if read_dashboard_playback_paused():
                continue
            try:
                sp_ctrl.update(spotify_features, stable_mood=mood)
            except Exception as exc:
                logger.warning("Spotify update failed: %s", exc)
