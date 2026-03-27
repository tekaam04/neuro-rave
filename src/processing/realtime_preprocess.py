import numpy as np
from scipy.signal import butter, lfilter, iirnotch

from src.streaming.lslbridge import LSLConsumer
from src.processing.fifo import MirrorCircleBuffer
import src.constants as const

# ── Frequency bands (Hz) ─────────────────────────────────────────────────────

THETA = (4, 8)
ALPHA = (8, 13)
BETA  = (13, 30)
GAMMA = (30, 100)

OVERLAP = 0.5

# ── Filter utilities ─────────────────────────────────────────────────────────

def bandpass(data: np.ndarray, low: float, high: float, fs: int) -> np.ndarray:
    b, a = butter(4, [low / (fs / 2), high / (fs / 2)], btype="band")
    return lfilter(b, a, data, axis=0)


def notch(data: np.ndarray, freq: float, fs: int, Q: float = 30) -> np.ndarray:
    b, a = iirnotch(freq / (fs / 2), Q)
    return lfilter(b, a, data, axis=0)


def bandpower(data: np.ndarray) -> np.ndarray:
    """Mean power per channel. Returns shape (n_channels,)."""
    return np.mean(data ** 2, axis=0)


# ── Processor ────────────────────────────────────────────────────────────────

class EEGProcessor:
    """
    Real-time EEG feature extractor backed by a MirrorCircleBuffer.

    Reads chunks from an LSLConsumer, fills the buffer, and on each full
    window computes band powers and derived features.
    """

    def __init__(self, window_seconds: float = 1.0) -> None:
        self.buffer = MirrorCircleBuffer.from_seconds(
            seconds=window_seconds,
            sample_rate=const.SAMPLE_RATE,
            n_channels=const.N_CHANNELS,
        )
        self.step_samples = int(self.buffer.size * (1 - OVERLAP))

        # history — 2D arrays: each row is one sample, columns are channels
        # shape grows as (n_windows * window_size, n_channels)
        self.theta_hist: list[np.ndarray] = []  # list of (window_size, n_channels)
        self.alpha_hist: list[np.ndarray] = []
        self.beta_hist:  list[np.ndarray] = []
        self.gamma_hist: list[np.ndarray] = []

    def get_history(self, band: str) -> np.ndarray:
        """Return full sample-by-sample history for a band as (n_samples, n_channels)."""
        hist = getattr(self, f"{band}_hist")
        if not hist:
            return np.empty((0, const.N_CHANNELS))
        return np.concatenate(hist, axis=0)

    def process_window(self) -> dict:
        """
        Run preprocessing and feature extraction on the current buffer.
        Returns a dict of features for this window.
        """
        data = self.buffer.data  # (window_size, n_channels)

        # preprocessing
        data = notch(data, 60, const.SAMPLE_RATE)
        data = bandpass(data, 1, 100, const.SAMPLE_RATE)

        # band-filtered signals — each is (window_size, n_channels)
        theta = bandpass(data, *THETA, const.SAMPLE_RATE)
        alpha = bandpass(data, *ALPHA, const.SAMPLE_RATE)
        beta  = bandpass(data, *BETA,  const.SAMPLE_RATE)
        gamma = bandpass(data, *GAMMA, const.SAMPLE_RATE)

        # store full sample-by-sample filtered data
        self.theta_hist.append(theta.copy())
        self.alpha_hist.append(alpha.copy())
        self.beta_hist.append(beta.copy())
        self.gamma_hist.append(gamma.copy())

        # per-channel band powers for this window
        theta_power = bandpower(theta)
        alpha_power = bandpower(alpha)
        beta_power  = bandpower(beta)
        gamma_power = bandpower(gamma)

        # derived features
        theta_beta = np.where(beta_power > 0, theta_power / beta_power, 0)

        alpha_sup = np.zeros(const.N_CHANNELS)
        if len(self.alpha_hist) > 5:
            baseline_data = np.concatenate(self.alpha_hist[:5], axis=0)  # first 5 windows
            baseline = np.mean(baseline_data ** 2, axis=0)
            alpha_sup = np.where(baseline > 0, (baseline - alpha_power) / baseline * 100, 0)

        return {
            "theta": theta_power,
            "alpha": alpha_power,
            "beta":  beta_power,
            "gamma": gamma_power,
            "theta_beta_ratio": theta_beta,
            "alpha_suppression": alpha_sup,
        }


# ── Entry point ──────────────────────────────────────────────────────────────

def run(simulate: bool = False) -> None:
    processor = EEGProcessor()

    if simulate:
        print("Running simulated EEG")
        t = 0.0
        dt = 1.0 / const.SAMPLE_RATE
        while True:
            sample = np.sin(2 * np.pi * 10 * t) + 0.5 * np.random.randn(const.N_CHANNELS)
            processor.buffer.add_sample(sample)
            t += dt

            if processor.buffer.full:
                features = processor.process_window()
                tb = features["theta_beta_ratio"]
                a_sup = features["alpha_suppression"]
                print(f"Theta/Beta: {tb.mean():.2f} | Alpha Suppression: {a_sup.mean():.1f}%")
    else:
        print("Searching for LSL EEG stream...")
        consumer = LSLConsumer("EEG")
        print(f"Connected — {const.N_CHANNELS} channels @ {const.SAMPLE_RATE} Hz")

        while True:
            samples, timestamps = consumer.get_chunk(max_samples=const.WINDOW_SIZE)

            if len(samples) == 0:
                continue

            processor.buffer.add_chunk(samples)

            if processor.buffer.full:
                features = processor.process_window()
                tb = features["theta_beta_ratio"]
                a_sup = features["alpha_suppression"]
                print(f"Theta/Beta: {tb.mean():.2f} | Alpha Suppression: {a_sup.mean():.1f}%")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args()
    run(simulate=args.simulate)
