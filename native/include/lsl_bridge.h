#pragma once

/*
 * lsl_bridge.h — C++ classes mirroring src/streaming/lslbridge.py
 *
 * Classes:
 *   TCPSource            → lslbridge.py  TCPSource
 *   BioSemi24BitDecoder  → lslbridge.py  BioSemi24BitDecoder
 *   LSLPublisher         → lslbridge.py  LSLPublisher
 *   LSLConsumer          → lslbridge.py  LSLConsumer
 *   LSLBridge            → lslbridge.py  LSLBridge
 */

#include <lsl/lsl_c.h>

#include <cstdint>
#include <string>
#include <thread>
#include <utility>
#include <vector>


/* ── TCPSource ───────────────────────────────────────────────────────────────
 * Blocking TCP socket to the BioSemi hardware.
 * Mirrors: TCPSource.__init__ / connect / recv_exact
 */
class TCPSource {
public:
    TCPSource(const std::string& host, int port);
    ~TCPSource();

    /* Block until connected (retries every 2 s).  Raises on fatal error. */
    void connect();

    /* Read exactly n_bytes from the socket into buf.
     * Returns 0 on success, -1 if the connection was closed or errored. */
    int recv_exact(uint8_t* buf, int n_bytes);

    /* Close the underlying socket. */
    void disconnect();

private:
    std::string host_;
    int         port_;
    int         sockfd_ = -1;
};


/* ── BioSemi24BitDecoder ─────────────────────────────────────────────────────
 * Decodes a raw sample block (n_channels × 3 bytes, 24-bit LE signed)
 * into a vector of floats.
 * Mirrors: BioSemi24BitDecoder.__init__ / decode_block
 */
class BioSemi24BitDecoder {
public:
    explicit BioSemi24BitDecoder(int n_channels);

    /* Decode one sample block.  raw must point to n_channels * 3 bytes.
     * Returns a vector of length n_channels. */
    std::vector<float> decode_block(const uint8_t* raw) const;

    int sample_block_size() const { return n_channels_ * 3; }
    int n_channels()        const { return n_channels_; }

private:
    int n_channels_;
};


/* ── LSLPublisher ────────────────────────────────────────────────────────────
 * Wraps an LSL StreamOutlet and exposes push_sample().
 * Mirrors: LSLPublisher.__init__ / push_sample
 */
class LSLPublisher {
public:
    LSLPublisher(const std::string& name,
                 const std::string& stream_type,
                 int                n_channels,
                 int                sample_rate,
                 const std::string& source_id);
    ~LSLPublisher();

    /* Push one sample (vector of length n_channels) to the LSL outlet. */
    void push_sample(const std::vector<float>& sample);

private:
    lsl_outlet outlet_ = nullptr;
};


/* ── LSLConsumer ─────────────────────────────────────────────────────────────
 * Resolves an LSL stream by type and exposes get_sample / get_chunk.
 * Mirrors: LSLConsumer.__init__ / get_sample / get_chunk
 */
class LSLConsumer {
public:
    explicit LSLConsumer(const std::string& stream_type = "EEG");
    ~LSLConsumer();

    /* Pull one sample.
     * Returns {timestamp, sample_values}. */
    std::pair<double, std::vector<float>> get_sample();

    /* Pull up to max_samples samples (non-blocking if max_samples > 0).
     * Returns {timestamps[], samples[]}
     * where samples[i] is a vector of n_channels floats for sample i. */
    std::pair<std::vector<double>, std::vector<std::vector<float>>>
        get_chunk(int max_samples = 512);

private:
    lsl_inlet inlet_ = nullptr;
    int       n_channels_ = 0;
};


/* ── LSLBridge ───────────────────────────────────────────────────────────────
 * Orchestrates TCPSource → BioSemi24BitDecoder → LSLPublisher on a thread.
 * Mirrors: LSLBridge.__init__ / start
 */
class LSLBridge {
public:
    LSLBridge(TCPSource&           tcp,
              BioSemi24BitDecoder& decoder,
              LSLPublisher&        publisher);

    /* Connect TCP (blocking), then start the streaming daemon thread. */
    void start();

private:
    TCPSource&           tcp_;
    BioSemi24BitDecoder& decoder_;
    LSLPublisher&        publisher_;
    std::thread          thread_;

    static void stream_loop(TCPSource*           tcp,
                            BioSemi24BitDecoder* decoder,
                            LSLPublisher*        publisher);
};
