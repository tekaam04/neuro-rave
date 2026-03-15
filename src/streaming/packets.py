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
    alpha:     float
    beta:      float
    type:      str = field(default="features", init=False)

    def to_json(self) -> str: 
        return json.dumps(asdict(self))