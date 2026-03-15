"""
WebSocket server that pulls EEG chunks from an LSL stream and broadcasts
them to all connected dashboard clients once per second.

Packet schema (JSON):
    {
        "timestamp":   float,      # LSL timestamp of the first sample
        "sample_rate": int,
        "n_channels":  int,
        "channels":    number[][]  # columnar — one array per channel
    }

Run standalone (for development):
    uvicorn src.streaming.ws_server:app --host 0.0.0.0 --port 8765 --reload

Or start from main.py in a background thread via start_ws_server().
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Set

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pylsl import StreamInlet, resolve_stream

from ..constants import N_CHANNELS, SAMPLE_RATE, WINDOW_SIZE

logger = logging.getLogger(__name__)

# ── connected clients ──────────────────────────────────────────────────────────

_clients: Set[WebSocket] = set()


async def _broadcast(payload: str) -> None:
    dead: Set[WebSocket] = set()
    for ws in list(_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


# ── LSL pull loop ──────────────────────────────────────────────────────────────

async def _lsl_loop() -> None:
    """Resolve an LSL EEG stream, pull WINDOW_SIZE samples per second, broadcast."""
    loop = asyncio.get_event_loop()

    logger.info("Resolving LSL EEG stream…")
    streams = await loop.run_in_executor(None, lambda: resolve_stream("type", "EEG"))
    inlet = StreamInlet(streams[0])
    logger.info("LSL stream resolved — broadcasting at ~1 packet/s")

    while True:
        chunk, timestamps = await loop.run_in_executor(
            None, lambda: inlet.pull_chunk(max_samples=WINDOW_SIZE)
        )

        if not chunk or not _clients:
            await asyncio.sleep(0.05)
            continue

        arr = np.array(chunk, dtype=np.float32)  # (n_samples, n_channels)

        payload = json.dumps({
            "timestamp":   float(timestamps[0]),
            "sample_rate": SAMPLE_RATE,
            "n_channels":  N_CHANNELS,
            "channels":    arr.T.tolist(),  # columnar: [[ch0…], [ch1…], …]
        })

        await _broadcast(payload)
        await asyncio.sleep(0.9)  # pace to ~1 packet/s


# ── FastAPI app ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    task = asyncio.create_task(_lsl_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=_lifespan)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)
    logger.info("Dashboard client connected  (total: %d)", len(_clients))
    try:
        # Keep the connection open; data is pushed by _lsl_loop
        while True:
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
        logger.info("Dashboard client disconnected (total: %d)", len(_clients))


# ── helper for main.py ─────────────────────────────────────────────────────────

def start_ws_server(host: str = "0.0.0.0", port: int = 8765) -> None:
    """Launch the WebSocket server in a background thread (call from main.py)."""
    import threading
    import uvicorn

    def _run() -> None:
        uvicorn.run(app, host=host, port=port, log_level="info")

    thread = threading.Thread(target=_run, daemon=True, name="ws-server")
    thread.start()
    logger.info("WebSocket server started on ws://%s:%d/ws", host, port)
