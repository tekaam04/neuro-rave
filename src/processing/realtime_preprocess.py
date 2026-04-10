import os
import logging
import numpy as np
from scipy.signal import butter, lfilter, iirnotch
from src.streaming.lslbridge import LSLConsumer
from src.processing.fifo import MirrorCircleFIFO
import src.constants as const

logger = logging.getLogger(__name__)
THETA = (4, 8)
ALPHA = (8, 13)
BETA  = (13, 30)
GAMMA = (30, 100)

OVERLAP = 0.5


def bandpass(data, low, high, fs):
    b, a = butter(4, [low / (fs / 2), high / (fs / 2)], btype="band")
    return lfilter(b, a, data, axis=0)


def notch(data, freq, fs, Q=30):
    b, a = iirnotch(freq / (fs / 2), Q)
    return lfilter(b, a, data, axis=0)


def bandpower(data):
    """Mean power per channel. Returns shape (n_channels,)."""
    return np.mean(data ** 2, axis=0)



class EEGProcessor:
    """
    Real-time EEG feature extractor backed by a MirrorCircleFIFO.

    Reads chunks from an LSLConsumer, fills the buffer, and on each full
    window computes band powers and derived features.
    """

    def __init__(self, window_seconds=1.0):
        self.buffer = MirrorCircleFIFO.from_seconds(
            seconds=window_seconds,
            sample_rate=const.SAMPLE_RATE,
            n_channels=const.N_CHANNELS,
        )
        self.step_samples = int(self.buffer.size * (1 - OVERLAP))

        # history - 2D arrays: each row is one sample, columns are channels
        # shape grows as (n_windows * window_size, n_channels)
        self.theta_hist = []
        self.alpha_hist = []
        self.beta_hist  = []
        self.gamma_hist = []

    def get_history(self, band):
        """Return full sample-by-sample history for a band as (n_samples, n_channels)."""
        hist = getattr(self, "{}_hist".format(band))
        if not hist:
            return np.empty((0, const.N_CHANNELS))
        return np.concatenate(hist, axis=0)

    def process_window(self):
        """
        Run preprocessing and feature extraction on the current buffer.
        Returns a dict of features for this window.
        """
        data = self.buffer.data  # (window_size, n_channels)

        # preprocessing
        data = notch(data, 60, const.SAMPLE_RATE)
        data = bandpass(data, 1, 100, const.SAMPLE_RATE)

        # band-filtered signals - each is (window_size, n_channels)
        theta = bandpass(data, THETA[0], THETA[1], const.SAMPLE_RATE)
        alpha = bandpass(data, ALPHA[0], ALPHA[1], const.SAMPLE_RATE)
        beta  = bandpass(data, BETA[0],  BETA[1],  const.SAMPLE_RATE)
        gamma = bandpass(data, GAMMA[0], GAMMA[1], const.SAMPLE_RATE)

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



def run(simulate=False):
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
                print("Theta/Beta: {:.2f} | Alpha Suppression: {:.1f}%".format(tb.mean(), a_sup.mean()))
    else:
        print("Searching for LSL EEG stream...")
        consumer = LSLConsumer("EEG")
        print("Connected - {} channels @ {} Hz".format(const.N_CHANNELS, const.SAMPLE_RATE))

        while True:
            samples, timestamps = consumer.get_chunk(max_samples=const.WINDOW_SIZE)

            if len(samples) == 0:
                continue

            processor.buffer.add_chunk(samples)

            if processor.buffer.full:
                features = processor.process_window()
                tb = features["theta_beta_ratio"]
                a_sup = features["alpha_suppression"]
                print("Theta/Beta: {:.2f} | Alpha Suppression: {:.1f}%".format(tb.mean(), a_sup.mean()))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args()
    run(simulate=args.simulate)
