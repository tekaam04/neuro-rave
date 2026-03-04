from abc import ABC, abstractmethod
import numpy as np
import warnings
import scipy.signal as signal

def is_power_of_two(n):
    return (n != 0) and (n & (n - 1) == 0)

def apply_window(data, window_type="hann"):
    n_samples = data.shape[0]

    window_map = {
        "hann": signal.windows.hann,
        "hanning": signal.windows.hann,  # alias
        "hamming": signal.windows.hamming,
        "blackman": signal.windows.blackman,
        "bartlett": signal.windows.bartlett,
        "flattop": signal.windows.flattop,
        "boxcar": signal.windows.boxcar,
    }

    if window_type not in window_map:
        raise ValueError(f"Unsupported window type: {window_type}")

    window = window_map[window_type](n_samples)
    return data * window[:, None]

# can only add data which pushes out the oldest sample, you can apply window to data but not modify it directly, data is read only, you can only add samples to it
class Buffer(ABC):
    def __init__(self, size, n_channels):
        if not is_power_of_two(size):
            warnings.warn("Buffer size should be a power of 2 for optimal FFT performance.")
        self.size = size
        self.n_channels = n_channels
        # self._data = np.zeros((size, n_channels))

    @abstractmethod
    def add_sample(self, sample):
        pass

    @abstractmethod
    @property
    def data(self):
        pass

# not efficient, write operations are O(n) but it uses minimal memory, you can apply window to data but not modify it directly, data is read only, you can only add samples to it
class RollBuffer(Buffer):
    def __init__(self, size, n_channels):
        super().__init__(size, n_channels)
        self._data = np.zeros((size, n_channels))

    def add_sample(self, sample):
        if len(sample) != self.n_channels:
            raise ValueError(f"Sample must have {self.n_channels} channels.")
        self._data = np.roll(self._data, -1, axis=0)
        self._data[-1] = sample

    @property
    def data(self):
        return self._data
    
# inefficient for read operations, write operations are O(1) but it uses minimal memory, you can apply window to data but not modify it directly, data is read only, you can only add samples to it
class CircularBuffer(Buffer):
    def __init__(self, size, n_channels):
        super().__init__(size, n_channels)
        self._data = np.zeros((size, n_channels))
        self._index = 0

    def add_sample(self, sample):
        if len(sample) != self.n_channels:
            raise ValueError(f"Sample must have {self.n_channels} channels.")
        self._data[self._index] = sample
        self._index = (self._index + 1) % self.size

    @property
    def data(self):
        # Return data in the correct order (oldest to newest)
        return np.roll(self._data, -self._index, axis=0)

# ultra efficient time wise, all operations are O(1) but it uses double the memory of a normal buffer, you can apply window to data but not modify it directly, data is read only, you can only add samples to it
class DoubleCircularBuffer(Buffer):
    def __init__(self, size, n_channels):
        super().__init__(size, n_channels)
        self._data = np.zeros((size * 2, n_channels))
        self._index = 0

    def add_sample(self, sample):
        if len(sample) != self.n_channels:
            raise ValueError(f"Sample must have {self.n_channels} channels.")
        self._data[self._index] = sample
        self._data[self._index + self.size] = sample  # Mirror the data
        self._index = (self._index + 1) % self.size

    @property
    def data(self):
        # Return data in the correct order (oldest to newest)
        return self._data[self._index:self._index + self.size]