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
# --- BEGIN agent-added: CORS + Spotify REST routes on same app as /ws ---
from fastapi.middleware.cors import CORSMiddleware

from scipy.signal import butter, lfilter, iirnotch
from src.api.spotify_routes import router as spotify_router
import src.constants as const
from src.streaming.lslbridge import LSLConsumer
from src.streaming.packets import RawPacket, FeaturesPacket
from src.processing.fifo import MirrorCircleFIFO

logger = logging.getLogger(__name__)


class EEGWebSocketServer:
    def __init__(self, host: str = const.WS_HOST, port: int = const.WS_PORT) -> None:
        self.host = host
        self.port = port

        self._clients:  Set[WebSocket]     = set()
        self._consumer: LSLConsumer | None = None
        self._features_buf = MirrorCircleFIFO(size=const.WINDOW_SIZE, n_channels=const.N_CHANNELS)
        self._features_dirty = False
        self._energy_history: list[float] = []

        self.app = FastAPI(lifespan=self._lifespan)
        # --- BEGIN agent-added: CORS + mount /spotify/* routers ---
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.app.include_router(spotify_router)
        # --- END agent-added ---
        self.app.add_api_websocket_route("/ws", self._ws_endpoint)

    # ── Lifespan ───────────────────────────────────────────────────────────────

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncGenerator[None, None]:
        """Start all broadcast loops on app startup; cancel them on shutdown."""
        tasks = [
            asyncio.create_task(self._raw_loop()),
            asyncio.create_task(self._features_loop()),
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

            # Feed features buffer from the same data
            self._features_buf.add_chunk(arr)
            self._features_dirty = True

            packet = RawPacket(
                timestamp=float(timestamps[0]),
                channels=arr.T.tolist(),  # columnar: [[ch0…], [ch1…], …]
            )

            await self._broadcast(packet.to_json())
            # logger.info("broadcast sent to %d client(s)", len(self._clients))
            await asyncio.sleep(0.9)  # pace to ~1 packet/s

    # ── Features broadcast ────────────────────────────────────────────────────

    async def _features_loop(self) -> None:
        """Compute EEG features from the shared buffer and broadcast every ~1s."""
        loop = asyncio.get_event_loop()
        fs = const.SAMPLE_RATE

        logger.info("Features broadcast loop active")

        def _bandpower(d, lo, hi):
            b, a = butter(4, [lo / (fs / 2), hi / (fs / 2)], btype="band")
            filtered = lfilter(b, a, d, axis=0)
            return np.mean(filtered ** 2, axis=0)

        while True:
            await asyncio.sleep(1.0)

            if not self._features_dirty or not self._features_buf.full or not self._clients:
                continue

            self._features_dirty = False
            data = self._features_buf.data.astype(np.float32)

            # Run DSP in executor to avoid blocking the event loop
            def _compute(data: np.ndarray) -> FeaturesPacket:
                # Preprocessing
                b_notch, a_notch = iirnotch(60 / (fs / 2), 30)
                d = lfilter(b_notch, a_notch, data, axis=0)
                b_bp, a_bp = butter(4, [1 / (fs / 2), 100 / (fs / 2)], btype="band")
                d = lfilter(b_bp, a_bp, d, axis=0)

                theta_power = _bandpower(d, 4, 8)
                beta_power = _bandpower(d, 13, 30)
                alpha_power = _bandpower(d, 8, 13)

                tb = np.where(beta_power > 0, theta_power / beta_power, 0.0)
                tb_mean = float(tb.mean())

                total_power = float(np.sum(d ** 2) + 1e-12)
                energy_raw = float(np.log10(total_power))
                self._energy_history.append(energy_raw)
                if len(self._energy_history) > 50:
                    self._energy_history.pop(0)
                e_min, e_max = min(self._energy_history), max(self._energy_history)
                if (e_max - e_min) < 1e-9:
                    energy = 0.5
                else:
                    energy = float(np.clip((energy_raw - e_min) / (e_max - e_min), 0.0, 1.0))

                focus = float(np.clip((3.0 - tb_mean) / 2.5, 0.0, 1.0))

                if energy < 0.3:
                    mood = "calm"
                elif energy < 0.7:
                    mood = "focus"
                else:
                    mood = "hype"

                return FeaturesPacket(
                    timestamp=0.0,
                    energy=energy,
                    focus=focus,
                    mood=mood,
                    theta_beta_ratio=tb_mean,
                    alpha_suppression=float(np.mean(alpha_power)),
                )

            packet = await loop.run_in_executor(None, _compute, data)
            await self._broadcast(packet.to_json())
            logger.info("features broadcast: mood=%s energy=%.2f focus=%.2f", packet.mood, packet.energy, packet.focus)

    # ── Entry point ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the WebSocket server in a daemon thread."""
        def _run() -> None:
            uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")

        thread = threading.Thread(target=_run, daemon=True, name="ws-server")
        thread.start()
        logger.info("WebSocket server started on ws://%s:%d/ws", self.host, self.port)
