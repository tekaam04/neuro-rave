"""
Packet dataclasses for the WebSocket server.

Each class represents one JSON message type sent to the dashboard.
Adding a new stream = add a new dataclass here + a loop in ws_server.py.

All packets share a `type` field so the React frontend can route them
with a switch statement.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class RawPacket:
    """One second of raw EEG samples, columnar per channel."""
    timestamp: float
    channels:  list[list[float]]   # shape: [n_channels][n_samples]
    type:      str = field(default="raw", init=False)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

@dataclass
class FeaturesPacket:
    timestamp: float
    energy:    float
    focus:     float
    mood:      str
    theta_beta_ratio:          float
    alpha_suppression:         float
    # Attention features from the current mood model. Defaults keep older
    # callers working; warm-up windows emit 0.0 until history fills.
    sustained_attention_index: float = 0.0
    energy_index:              float = 0.0
    is_attentive:              bool  = False
    sustained_streak_sec:      float = 0.0
    type:      str = field(default="features", init=False)

    def to_json(self) -> str:
        return json.dumps(asdict(self))