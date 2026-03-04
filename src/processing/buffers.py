from abc import ABC, abstractmethod
import numpy as np
import warnings
import scipy.signal as signal


def is_power_of_two(n):
    return (n != 0) and (n & (n - 1) == 0)


class Buffer(ABC):
    def __init__(self, size, n_channels, dtype=np.float32):
        if not is_power_of_two(size):
            warnings.warn("Buffer size should be a power of 2 for optimal FFT performance.")

        self.size = size
        self.n_channels = n_channels
        self.dtype = dtype
        self.full = False

    @abstractmethod
    def add_sample(self, sample):
        pass

    def add_chunk(self, chunk):
        chunk = np.asarray(chunk, dtype=self.dtype)
        for sample in chunk:
            self.add_sample(sample)

    @property
    @abstractmethod
    def data(self):
        pass

class CircularBuffer(Buffer):
    def __init__(self, size, n_channels, dtype=np.float32):
        super().__init__(size, n_channels, dtype)
        self._data = np.zeros((size, n_channels), dtype=dtype)
        self._index = 0

    def add_sample(self, sample):
        sample = np.asarray(sample, dtype=self.dtype)

        if sample.shape[0] != self.n_channels:
            raise ValueError(f"Sample must have {self.n_channels} channels.")

        self._data[self._index] = sample
        self._index = (self._index + 1) % self.size

        if self._index == 0:
            self.full = True

    def add_chunk(self, chunk):
        chunk = np.asarray(chunk, dtype=self.dtype)
        n = len(chunk)

        if n >= self.size:
            chunk = chunk[-self.size:]
            self._data[:] = chunk
            self._index = 0
            self.full = True
            return

        end = self._index + n
        if end <= self.size:
            self._data[self._index:end] = chunk
        else:
            first = self.size - self._index
            self._data[self._index:self.size] = chunk[:first]
            self._data[:end - self.size] = chunk[first:]

        self._index = end % self.size
        if end >= self.size:
            self.full = True

    @property
    def data(self):
        # Not yet full → simple slice (O(1))
        if not self.full:
            return self._data[:self._index]

        # Wrapped → must re-order (O(size))
        return np.concatenate(
            (self._data[self._index:], self._data[:self._index]),
            axis=0
        )

    @property
    def shape(self):
        if not self.full:
            return (self._index, self.n_channels)
        return (self.size, self.n_channels)

    def __array__(self):
        return self.data

    def __getitem__(self, item):
        return self.data[item]
    
class MirrorCircleBuffer(Buffer):
    def __init__(self, size, n_channels, dtype=np.float32):
        super().__init__(size, n_channels, dtype)
        self._data = np.zeros((size * 2, n_channels), dtype=dtype)
        self._index = 0

    def add_sample(self, sample):
        sample = np.asarray(sample, dtype=self.dtype)

        if sample.shape[0] != self.n_channels:
            raise ValueError(f"Sample must have {self.n_channels} channels.")

        self._data[self._index] = sample
        self._data[self._index + self.size] = sample

        self._index = (self._index + 1) % self.size

        if self._index == 0:
            self.full = True

    def add_chunk(self, chunk):
        chunk = np.asarray(chunk, dtype=self.dtype)
        n = len(chunk)

        if n >= self.size:
            # chunk fills entire buffer — just take the last `size` samples
            chunk = chunk[-self.size:]
            self._data[:self.size] = chunk
            self._data[self.size:] = chunk
            self._index = 0
            self.full = True
            return

        end = self._index + n
        if end <= self.size:
            self._data[self._index:end] = chunk
            self._data[self._index + self.size:end + self.size] = chunk
        else:
            first = self.size - self._index
            self._data[self._index:self.size] = chunk[:first]
            self._data[self._index + self.size:self.size * 2] = chunk[:first]
            self._data[:end - self.size] = chunk[first:]
            self._data[self.size:end] = chunk[first:]

        self._index = end % self.size
        if end >= self.size:
            self.full = True

    @property
    def data(self):
        if not self.full:
            return self._data[:self._index]

        return self._data[self._index:self._index + self.size]

    @property
    def shape(self):
        return (self.size, self.n_channels)

    def __array__(self):
        return self.data

    def __getitem__(self, item):
        return self.data[item]


def apply_window(data, window_type="hann"):
    n = data.shape[0]

    window_map = {
        "hann": signal.windows.hann,
        "hanning": signal.windows.hann,
        "hamming": signal.windows.hamming,
        "blackman": signal.windows.blackman,
        "bartlett": signal.windows.bartlett,
        "flattop": signal.windows.flattop,
        "boxcar": signal.windows.boxcar,
    }

    if window_type not in window_map:
        raise ValueError(f"Unsupported window type: {window_type}")

    window = window_map[window_type](n)
    return data * window[:, None]