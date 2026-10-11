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
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator, Set

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
# --- BEGIN agent-added: CORS + Spotify REST routes on same app as /ws ---
from fastapi.middleware.cors import CORSMiddleware

from src.api.spotify_routes import router as spotify_router
import src.constants as const
from src.music_gen.spotify_controller import MoodStabilizer, NeuroFeatures, propose_mood
from src.processing.dashboard_features import DashboardFeatureState
from src.processing.mood_prepare import stabilizer_outputs_for_mood
from src.processing.neuro_raw_inputs import neuro_raw_inputs_for_stabilizer
from src.processing.spotify_feature_pipeline import SpotifyFeaturePipeline
from src.streaming.packets import RawPacket, FeaturesPacket
from src.processing.fifo import MirrorCircleFIFO

if TYPE_CHECKING:
    from src.streaming.lslbridge import LSLConsumer

logger = logging.getLogger(__name__)


class EEGWebSocketServer:
    def __init__(
        self,
        host: str = const.WS_HOST,
        port: int = const.WS_PORT,
        use_internal_lsl_source: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.use_internal_lsl_source = bool(use_internal_lsl_source)

        self._clients:  Set[WebSocket]     = set()
        self._consumer: LSLConsumer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._features_buf = MirrorCircleFIFO(size=const.WINDOW_SIZE, n_channels=const.N_CHANNELS)
        self._features_dirty = False
        self._dashboard_features = DashboardFeatureState()
        self._mood_stabilizer = MoodStabilizer()
        self._band_pipeline: SpotifyFeaturePipeline | None = (
            SpotifyFeaturePipeline()
            if const.NEURO_FEATURE_SOURCE == "band_pipeline"
            else None
        )
        logger.info(
            "NEURO_FEATURE_SOURCE=%s | NEURO_APPLY_STABILIZER_SMOOTH=%s",
            const.NEURO_FEATURE_SOURCE,
            const.NEURO_APPLY_STABILIZER_SMOOTH,
        )

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
        self.app.post("/features")(self._receive_features) # AAB. Added

    # ── Lifespan ───────────────────────────────────────────────────────────────

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncGenerator[None, None]:
        """Start all broadcast loops on app startup; cancel them on shutdown."""
        tasks = []

        if not const.SIMULATE:
            tasks.extend([
                asyncio.create_task(self._raw_loop()),
                asyncio.create_task(self._features_loop()),
            ])
        else:
            logger.info("SIMULATE=true — skipping LSL raw/features loops; using /features POST input.")
        self._loop = asyncio.get_running_loop()
        tasks = []
        if self.use_internal_lsl_source:
            tasks = [
                asyncio.create_task(self._raw_loop()),
                asyncio.create_task(self._features_loop()),
            ]
        yield
        for task in tasks:
            task.cancel()
        self._loop = None

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
    
    async def _receive_features(self, payload: dict) -> dict: # AAB. Added to integrate main features duing simulation
        """Receive externally computed features and broadcast them to WebSocket clients."""
        packet = FeaturesPacket(
            timestamp=float(payload.get("timestamp", 0.0)),
            energy=float(payload["energy"]),
            focus=float(payload["focus"]),
            mood=str(payload.get("mood", "unknown")),
            theta_beta_ratio=float(payload.get("theta_beta_ratio", 0.0)),
            alpha_suppression=float(payload.get("alpha_suppression", 0.0)),
            sustained_attention_index=float(payload.get("sustained_attention_index", 0.0)),
            energy_index=float(payload.get("energy_index", 0.0)),
            is_attentive=bool(payload.get("is_attentive", False)),
            sustained_streak_sec=float(payload.get("sustained_streak_sec", 0.0)),
        )

        await self._broadcast(packet.to_json())
        logger.info(
            "external features broadcast: source=%s mood=%s energy=%.2f focus=%.2f",
            str(payload.get("source", "unknown")),
            packet.mood,
            packet.energy,
            packet.focus,
        )
        return {"ok": True}

    # ── Broadcast loops ────────────────────────────────────────────────────────

    async def _raw_loop(self) -> None:
        """Pull raw EEG chunks from LSL and broadcast once per second."""
        loop = asyncio.get_event_loop()
        from src.streaming.lslbridge import LSLConsumer

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

    def _compute_features_packet(self, data: np.ndarray) -> FeaturesPacket:
        """Band features + attention indices; same module as ``main.EEGProcessor``."""
        wf = self._dashboard_features.process_window(np.asarray(data, dtype=np.float32))

        feat = wf.to_spotify_feature_dict(
            energy_index=wf.energy_index,
            sustained_attention_index=wf.sustained_attention_index,
        )
        raw_energy, raw_focus = neuro_raw_inputs_for_stabilizer(
            feat,
            band_pipeline=self._band_pipeline,
        )

        se, sf, d_e = stabilizer_outputs_for_mood(
            self._mood_stabilizer, raw_energy, raw_focus
        )
        proposed = propose_mood(NeuroFeatures(energy=se, focus=sf, d_energy=d_e))
        mood = self._mood_stabilizer.majority_mood(proposed)

        return FeaturesPacket(
            timestamp=0.0,
            energy=se,
            focus=sf,
            mood=mood,
            theta_beta_ratio=wf.theta_beta_mean,
            alpha_suppression=wf.alpha_sup_mean,
            sustained_attention_index=raw_focus,
            energy_index=float(wf.energy_index) if wf.energy_index is not None else 0.0,
            is_attentive=bool(wf.is_attentive),
            sustained_streak_sec=float(wf.sustained_streak_sec),
        )

    async def _features_loop(self) -> None:
        """Compute EEG features from the shared buffer and broadcast every ~1s."""
        loop = asyncio.get_event_loop()

        logger.info("Features broadcast loop active")

        while True:
            await asyncio.sleep(1.0)

            if not self._features_dirty or not self._features_buf.full or not self._clients:
                continue

            self._features_dirty = False
            data = self._features_buf.data.astype(np.float32)

            packet = await loop.run_in_executor(None, self._compute_features_packet, data)
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

    def publish_raw(self, samples: np.ndarray, timestamp: float | None = None) -> None:
        """Broadcast one raw packet from an external producer (e.g., main loop)."""
        loop = self._loop
        if loop is None or not self._clients:
            return
        arr = np.asarray(samples, dtype=np.float32)
        if arr.ndim != 2:
            return
        packet = RawPacket(
            timestamp=float(timestamp if timestamp is not None else time.time()),
            channels=arr.T.tolist(),
        )
        asyncio.run_coroutine_threadsafe(self._broadcast(packet.to_json()), loop)

    def publish_features(
        self,
        *,
        energy: float,
        focus: float,
        mood: str,
        alpha_suppression: float,
        sustained_streak_sec: float,
        is_attentive: bool,
        sustained_attention_index: float,
        energy_index: float | None,
        theta_beta_ratio: float = 0.0,
        timestamp: float | None = None,
    ) -> None:
        """Broadcast one feature packet from an external producer (e.g., main loop)."""
        loop = self._loop
        if loop is None or not self._clients:
            return
        packet = FeaturesPacket(
            timestamp=float(timestamp if timestamp is not None else time.time()),
            energy=float(energy),
            focus=float(focus),
            mood=str(mood),
            theta_beta_ratio=float(theta_beta_ratio),
            alpha_suppression=float(alpha_suppression),
            sustained_attention_index=float(sustained_attention_index),
            energy_index=float(energy_index) if energy_index is not None else 0.0,
            is_attentive=bool(is_attentive),
            sustained_streak_sec=float(sustained_streak_sec),
        )
        asyncio.run_coroutine_threadsafe(self._broadcast(packet.to_json()), loop)
