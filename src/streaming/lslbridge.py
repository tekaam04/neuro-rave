import os
import socket
import threading
from pathlib import Path

import numpy as np


def _ensure_pylsl_lib_path() -> None:
    """Set PYLSL_LIB before importing pylsl.

    On macOS, ``DYLD_LIBRARY_PATH`` is often ignored (SIP); pylsl loads via
    ``PYLSL_LIB`` or its bundled search path. Homebrew installs
    ``liblsl*.dylib`` under ``/opt/homebrew/lib`` or ``/usr/local/lib``.
    """
    if os.environ.get("PYLSL_LIB"):
        return
    for libdir in (Path("/opt/homebrew/lib"), Path("/usr/local/lib")):
        if not libdir.is_dir():
            continue
        for pattern in ("liblsl*.dylib", "liblsl.so*"):
            matches = sorted(libdir.glob(pattern))
            for cand in matches:
                if cand.is_file():
                    os.environ["PYLSL_LIB"] = str(cand.resolve())
                    return


_ensure_pylsl_lib_path()
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_stream

class TCPSource:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = None

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        print(f"Connected to TCP source at {self.host}:{self.port}")

    def recv_exact(self, n_bytes):
        buf = b''
        while len(buf) < n_bytes:
            chunk = self.socket.recv(n_bytes - len(buf))
            if not chunk:
                raise ConnectionError("TCP connection closed")
            buf += chunk
        return buf

class BioSemi24BitDecoder:
    def __init__(self, n_channels, dtype=np.float32):
        self.n_channels = n_channels
        self.bytes_per_sample = 3
        self.sample_block_size = n_channels * self.bytes_per_sample
        self.dtype = dtype

    def decode_block(self, raw_block):
        sample = np.empty(self.n_channels, dtype=self.dtype)

        for ch in range(self.n_channels):
            start = ch * 3
            three_bytes = raw_block[start:start+3]
            value = int.from_bytes(three_bytes, byteorder='little', signed=True)
            sample[ch] = value

        return sample

class LSLPublisher:
    def __init__(self, name, stream_type, n_channels, sample_rate, source_id):
        info = StreamInfo(
            name=name,
            type=stream_type,
            channel_count=n_channels,
            nominal_srate=sample_rate,
            channel_format='float32',
            source_id=source_id
        )
        self.outlet = StreamOutlet(info)

    def push_sample(self, sample):
        self.outlet.push_sample(sample.tolist())


class LSLConsumer:
    def __init__(self, stream_type="EEG"):
        streams = resolve_stream('type', stream_type)
        self._inlet = StreamInlet(streams[0])

    def get_sample(self):
        return self._inlet.pull_sample()

    def get_chunk(self, max_samples=512):
        return self._inlet.pull_chunk(max_samples=max_samples)
    
def _stream_loop(tcpsource, decoder, lslpub):
    while True:
        raw_block = tcpsource.recv_exact(decoder.sample_block_size)
        sample = decoder.decode_block(raw_block)
        lslpub.push_sample(sample)


class LSLBridge:
    def __init__(self, tcp, decoder, publisher):
        self.tcp = tcp
        self.decoder = decoder
        self.publisher = publisher
        self._thread = None

    def start(self):
        """Connect to TCP source (raises on failure), then start streaming thread."""
        self.tcp.connect()  # blocks until connected or raises
        self._thread = threading.Thread(
            target=_stream_loop,
            args=(self.tcp, self.decoder, self.publisher),
            daemon=True
        )
        self._thread.start()
