import socket
import struct
import numpy as np
from pylsl import StreamInfo, StreamOutlet, StreamInlet, resolve_stream
from src.streaming.config import HOST, PORT, BYTES_PER_SAMPLE, N_CHANNELS, SAMPLE_RATE


def start_lsl_stream():
    # lsl stream
    info = StreamInfo(
        name='BioSemiEEG',
        type='EEG',
        channel_count=N_CHANNELS,
        nominal_srate=SAMPLE_RATE,
        channel_format='float32',
        source_id='biosemi_tcp_bridge'
    )

    outlet = StreamOutlet(info)

    # connect to actiview
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))

    print("Connected to ActiView TCP")

    # Each sample = channels × 3 bytes
    sample_block_size = N_CHANNELS * BYTES_PER_SAMPLE

    buffer = b''

    # stream
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

def create_inlet():
    stream = resolve_stream('type', 'EEG')
    return StreamInlet(stream[0])

def get_chunk_from_stream(inlet):
    return inlet.pull_chunk(max_samples=512)