"""Map band features to Spotify ``NeuroFeatures`` (energy + focus).

Energy uses alpha-suppression (absolute linear map + session-relative min–max),
gamma arousal blend, and dual-timescale smoothing. Bounds and weights come from
``config/constants.json`` (with optional ``SPOTIFY_*`` env overrides for weights).
"""

from __future__ import annotations

import os
from collections import deque

import numpy as np

import src.constants as const
from src.music_gen.spotify_controller import NeuroFeatures
from src.processing.focus_map import focus_from_theta_beta_mean


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _hist_maxlen() -> int:
    base = int(getattr(const, "ENERGY_HISTORY_MAX", 96))
    try:
        v = int(os.environ.get("SPOTIFY_ENERGY_HISTORY_MAX", str(base)) or str(base))
        return max(24, min(v, 800))
    except ValueError:
        return max(24, min(base, 800))


class SpotifyFeaturePipeline:
    """Stateful pipeline (per-stream history). Instantiate one per EEG source."""

    def __init__(self) -> None:
        n = _hist_maxlen()
        self._energy_history: deque[float] = deque(maxlen=n)
        self._gamma_history: deque[float] = deque(maxlen=n)
        self._energy_slow_state: float | None = None

    def process(self, eeg_features: dict) -> NeuroFeatures:
        alpha_sup_mean = float(np.mean(eeg_features["alpha_suppression"]))

        lo_clip = float(const.ENERGY_RAW_CLIP_LOW)
        hi_clip = float(const.ENERGY_RAW_CLIP_HIGH)
        energy_raw = float(np.clip(alpha_sup_mean, lo_clip, hi_clip))
        self._energy_history.append(energy_raw)
        e_min = min(self._energy_history)
        e_max = max(self._energy_history)
        if (e_max - e_min) < 1e-9:
            energy_rel = 0.5
        else:
            energy_rel = float(np.clip((energy_raw - e_min) / (e_max - e_min), 0.0, 1.0))

        a_lo = float(const.ENERGY_ALPHA_SUP_PERCENT_LOW)
        a_hi = float(const.ENERGY_ALPHA_SUP_PERCENT_HIGH)
        if a_hi <= a_lo:
            a_hi = a_lo + 1e-3
        energy_abs = float(np.clip((alpha_sup_mean - a_lo) / (a_hi - a_lo), 0.0, 1.0))

        w_abs = float(const.ENERGY_BLEND_ABSOLUTE_WEIGHT)
        w_abs = max(0.0, min(w_abs, 1.0))
        energy_fast = w_abs * energy_abs + (1.0 - w_abs) * energy_rel

        gamma_mean = float(np.mean(eeg_features["gamma"]))
        gamma_raw = float(np.log1p(max(gamma_mean, 0.0)))
        self._gamma_history.append(gamma_raw)
        g_min, g_max = min(self._gamma_history), max(self._gamma_history)
        if (g_max - g_min) < 1e-12:
            g_norm = 0.5
        else:
            g_norm = float(np.clip((gamma_raw - g_min) / (g_max - g_min), 0.0, 1.0))

        w_g = _env_float("SPOTIFY_GAMMA_AROUSAL_WEIGHT", float(const.GAMMA_AROUSAL_WEIGHT))
        w_g = max(0.0, min(w_g, 0.45))
        energy_blend = (1.0 - w_g) * energy_fast + w_g * g_norm

        slow_alpha = _env_float("SPOTIFY_ENERGY_SLOW_ALPHA", float(const.ENERGY_SLOW_ALPHA))
        slow_alpha = max(0.005, min(slow_alpha, 0.5))
        w_fast = _env_float("SPOTIFY_ENERGY_FAST_WEIGHT", float(const.ENERGY_FAST_WEIGHT))
        w_fast = max(0.0, min(w_fast, 1.0))

        if self._energy_slow_state is None:
            self._energy_slow_state = energy_blend
        self._energy_slow_state = (
            slow_alpha * energy_blend + (1.0 - slow_alpha) * self._energy_slow_state
        )
        energy = float(
            np.clip(
                w_fast * energy_blend + (1.0 - w_fast) * self._energy_slow_state,
                0.0,
                1.0,
            )
        )

        tb_mean = float(np.mean(eeg_features["theta_beta_ratio"]))
        focus = focus_from_theta_beta_mean(tb_mean)

        # Blend alpha-suppression attention indices from the current mood model
        # when they're available. Warm-up windows return None -> skip the blend.
        e_idx = eeg_features.get("energy_index")
        if e_idx is not None:
            w_e = max(0.0, min(float(getattr(const, "ENERGY_ATTENTION_BLEND", 0.0)), 1.0))
            if w_e > 0.0:
                energy = float(np.clip((1.0 - w_e) * energy + w_e * float(e_idx), 0.0, 1.0))

        f_idx = eeg_features.get("sustained_attention_index")
        if f_idx is not None:
            w_f = max(0.0, min(float(getattr(const, "FOCUS_ATTENTION_BLEND", 0.0)), 1.0))
            if w_f > 0.0:
                focus = float(np.clip((1.0 - w_f) * focus + w_f * float(f_idx), 0.0, 1.0))

        return NeuroFeatures(energy=energy, focus=focus)
