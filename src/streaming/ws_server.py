"""
WebSocket server that pulls EEG data from LSL and broadcasts it to all
connected dashboard clients.

Packet schema (JSON):
    {
        "type":        str,        # packet kind, e.g. "raw"
        "timestamp":   float,      # LSL timestamp of the first sample
        "sample_rate": int,
        "n_channels":  int,
        "channels":    number[][]  # columnar — one array per channel
    }

Usage from main.py:
    server = EEGWebSocketServer()
    server.start()
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Set

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from src.streaming.lslbridge import LSLConsumer
from src.streaming.packets import RawPacket
import src.constants as const

logger = logging.getLogger(__name__)


class EEGWebSocketServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self.host = host
        self.port = port

        self._clients:  Set[WebSocket]     = set()
        self._consumer: LSLConsumer | None = None

        self.app = FastAPI(lifespan=self._lifespan)
        self.app.add_api_websocket_route("/ws", self._ws_endpoint)

    # ── Lifespan ───────────────────────────────────────────────────────────────

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncGenerator[None, None]:
        """Start all broadcast loops on app startup; cancel them on shutdown."""
        tasks = [
            asyncio.create_task(self._raw_loop()),
            # future loops go here, e.g.:
            # asyncio.create_task(self._features_loop()),
        ]
        yield
        for task in tasks:
            task.cancel()

    # ── Client management ──────────────────────────────────────────────────────

    async def _ws_endpoint(self, websocket: WebSocket) -> None:
        """One coroutine per connected dashboard client. Stays alive until disconnect."""
        await websocket.accept()
        self._clients.add(websocket)
        logger.info("Client connected  (total: %d)", len(self._clients))
        try:
            while True:
                await asyncio.sleep(10)  # data is pushed by broadcast loops
        except WebSocketDisconnect:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info("Client disconnected (total: %d)", len(self._clients))

    async def _broadcast(self, payload: str) -> None:
        """Send a JSON string to every connected client, pruning dead connections."""
        dead: Set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._clients.difference_update(dead)

    # ── Broadcast loops ────────────────────────────────────────────────────────

    async def _raw_loop(self) -> None:
        """Pull raw EEG chunks from LSL and broadcast once per second."""
        loop = asyncio.get_event_loop()

        logger.info("Resolving LSL EEG stream…")
        self._consumer = await loop.run_in_executor(None, LSLConsumer)
        logger.info("LSL stream resolved — raw broadcast active")

        while True:
            chunk, timestamps = await loop.run_in_executor(
                None, lambda: self._consumer.get_chunk(max_samples=const.WINDOW_SIZE)  # type: ignore[union-attr]
            )

            if not chunk:
                await asyncio.sleep(0.05)
                continue

            # logger.info("chunk=%d samples, clients=%d", len(chunk), len(self._clients))

            if not self._clients:
                await asyncio.sleep(0.05)
                continue

            arr = np.array(chunk, dtype=np.float32)  # (n_samples, n_channels)

            packet = RawPacket(
                timestamp=float(timestamps[0]),
                channels=arr.T.tolist(),  # columnar: [[ch0…], [ch1…], …]
            )

            await self._broadcast(packet.to_json())
            # logger.info("broadcast sent to %d client(s)", len(self._clients))
            await asyncio.sleep(0.9)  # pace to ~1 packet/s

    # ── Entry point ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the WebSocket server in a daemon thread."""
        def _run() -> None:
            uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")

        thread = threading.Thread(target=_run, daemon=True, name="ws-server")
        thread.start()
        logger.info("WebSocket server started on ws://%s:%d/ws", self.host, self.port)
