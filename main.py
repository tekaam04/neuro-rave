import threading
from src.streaming.lslbridge import start_lsl_stream, create_inlet, get_chunk_from_stream
from src.processing.test_dsp import apply_fft
from src.dashboard.test_plot import plot_fft


def build():
    thread = threading.Thread(target=start_lsl_stream, daemon=True)
    thread.start()


if __name__ == "__main__":
    build()
    inlet = create_inlet()
    while True:
        samples, timestamps = get_chunk_from_stream(inlet)
        if samples:
            sp = apply_fft(samples)
            sp[0] = 0 # eliminate DC component
            plot_fft(sp)