"""Map mean theta/beta ratio to a [0, 1] focus score for real-time EEG.

Higher focus ⇒ relatively more beta than theta (engaged / less “idle” theta).
Bounds come from ``config/constants.json`` (``FOCUS_THETA_BETA_*``).
"""

from __future__ import annotations

import src.constants as const


def focus_from_theta_beta_mean(tb_mean: float) -> float:
    lo = float(const.FOCUS_THETA_BETA_LOW)
    hi = float(const.FOCUS_THETA_BETA_HIGH)
    if hi <= lo:
        hi = lo + 1e-3
    x = (hi - float(tb_mean)) / (hi - lo)
    return max(0.0, min(1.0, x))
