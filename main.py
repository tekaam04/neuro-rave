import logging
import numpy as np
import matplotlib.pyplot as plt
from src.streaming.lslbridge import TCPSource, BioSemi24BitDecoder, LSLPublisher, LSLConsumer, LSLBridge
from src.streaming.ws_server import EEGWebSocketServer
from src.processing.fifo import MirrorCircleBuffer
import src.constants as const

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

if __name__ == "__main__":
    # ── LSL Bridge: TCP → decode → LSL stream ────────────────────────────
    tcp = TCPSource(const.BIOSEMI_HOST, const.BIOSEMI_PORT)
    decoder = BioSemi24BitDecoder(const.N_CHANNELS)
    publisher = LSLPublisher(
        "BioSemiEEG", "EEG", const.N_CHANNELS, const.SAMPLE_RATE, "biosemi_tcp_bridge"
    )

    bridge = LSLBridge(tcp, decoder, publisher)
    bridge.start()

    # ── WebSocket server: LSL → browser dashboard ────────────────────────
    ws = EEGWebSocketServer(host="0.0.0.0", port=8765)
    ws.start()

    # ── FFT test plot ────────────────────────────────────────────────────
    consumer = LSLConsumer("EEG")
    fifo = MirrorCircleBuffer(size=const.WINDOW_SIZE, n_channels=const.N_CHANNELS)

    plt.ion()
    while True:
        samples, ts = consumer.get_chunk()

        if len(samples) == 0:
            continue

        fifo.add_chunk(samples)

        if fifo.full:
            sp = np.fft.fft(fifo)
            sp[0] = 0

            plt.clf()
            plt.plot(sp.real)
            plt.pause(0.001)
