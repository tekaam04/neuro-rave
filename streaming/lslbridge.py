import socket
import struct
import numpy as np
from pylsl import StreamInfo, StreamOutlet

# =====================
# CONFIG
# =====================
HOST = "127.0.0.1"
PORT = 8888

N_CHANNELS = 32        # change to your montage
SAMPLE_RATE = 512      # change to your acquisition rate
BYTES_PER_SAMPLE = 3   # BioSemi = 24-bit

# =====================
# Setup LSL Stream
# =====================
info = StreamInfo(
    name='BioSemiEEG',
    type='EEG',
    channel_count=N_CHANNELS,
    nominal_srate=SAMPLE_RATE,
    channel_format='float32',
    source_id='biosemi_tcp_bridge'
)

outlet = StreamOutlet(info)

# =====================
# Connect to ActiView
# =====================
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((HOST, PORT))

print("Connected to ActiView TCP")

# Each sample = channels × 3 bytes
sample_block_size = N_CHANNELS * BYTES_PER_SAMPLE

buffer = b''

while True:
    buffer += sock.recv(4096)

    while len(buffer) >= sample_block_size:
        raw_sample = buffer[:sample_block_size]
        buffer = buffer[sample_block_size:]

        sample = []

        for ch in range(N_CHANNELS):
            start = ch * 3
            three_bytes = raw_sample[start:start+3]

            # Convert 24-bit little endian to int32
            value = int.from_bytes(three_bytes, byteorder='little', signed=True)

            # Convert to microvolts
            value = value * (1.0 / 32.0)

            sample.append(float(value))

        outlet.push_sample(sample)