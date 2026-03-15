import threading
from src.streaming.lslbridge import TCPSource, BioSemi24BitDecoder, LSLPublisher, LSLConsumer, LSLBridge
from src.processing.test_dsp import apply_fft
from src.processing.fifo import MirrorCircleFIFO
from src.dashboard.test_plot import plot_fft
import numpy as np
import matplotlib.pyplot as plt
import src.constants as const

if __name__ == "__main__":
    tcp = TCPSource(const.HOST, const.PORT)
    decoder = BioSemi24BitDecoder(const.N_CHANNELS)
    publisher = LSLPublisher("BioSemiEEG", "EEG", const.N_CHANNELS, const.SAMPLE_RATE, "biosemi_tcp_bridge")

    bridge = LSLBridge(tcp, decoder, publisher)
    bridge.start()  

    consumer = LSLConsumer("EEG")

    fifo = MirrorCircleFIFO(size=const.WINDOW_SIZE, n_channels=const.N_CHANNELS)

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