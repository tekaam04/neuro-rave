/*
 * lsl_bridge.cpp — C++ classes mirroring src/streaming/lslbridge.py
 *
 * Classes implemented here:
 *   TCPSource, BioSemi24BitDecoder, LSLPublisher, LSLConsumer, LSLBridge
 *
 * Usage (standalone binary — run from repo root):
 *   ./native/build/neuro_lsl_bridge [path/to/constants.json]
 */

#include "lsl_bridge.h"
#include "config.h"

#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <netinet/in.h>
#include <signal.h>
#include <stdexcept>
#include <stdio.h>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>


/* ═══════════════════════════════════════════════════════════════════════════
 * TCPSource
 * ═══════════════════════════════════════════════════════════════════════════ */

TCPSource::TCPSource(const std::string& host, int port)
    : host_(host), port_(port) {}

TCPSource::~TCPSource()
{
    disconnect();
}

void TCPSource::connect()
{
    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(static_cast<uint16_t>(port_));
    if (inet_pton(AF_INET, host_.c_str(), &addr.sin_addr) != 1)
        throw std::runtime_error("TCPSource: invalid host address: " + host_);

    while (true) {
        int fd = ::socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0)
            throw std::runtime_error(std::string("TCPSource: socket: ") + strerror(errno));

        if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0) {
            sockfd_ = fd;
            printf("[TCPSource] Connected to %s:%d\n", host_.c_str(), port_);
            return;
        }

        fprintf(stderr, "[TCPSource] Could not connect to %s:%d: %s — retrying in 2s\n",
                host_.c_str(), port_, strerror(errno));
        ::close(fd);
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
}

int TCPSource::recv_exact(uint8_t* buf, int n_bytes)
{
    int received = 0;
    while (received < n_bytes) {
        int r = static_cast<int>(::recv(sockfd_, buf + received,
                                        static_cast<size_t>(n_bytes - received), 0));
        if (r <= 0)
            return -1;
        received += r;
    }
    return 0;
}

void TCPSource::disconnect()
{
    if (sockfd_ >= 0) {
        ::close(sockfd_);
        sockfd_ = -1;
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
 * BioSemi24BitDecoder
 * ═══════════════════════════════════════════════════════════════════════════ */

BioSemi24BitDecoder::BioSemi24BitDecoder(int n_channels)
    : n_channels_(n_channels) {}

std::vector<float> BioSemi24BitDecoder::decode_block(const uint8_t* raw) const
{
    std::vector<float> sample(static_cast<size_t>(n_channels_));
    for (int ch = 0; ch < n_channels_; ++ch) {
        const uint8_t* p = raw + ch * 3;
        /* 24-bit little-endian signed integer */
        int32_t val = static_cast<int32_t>(p[0])
                    | (static_cast<int32_t>(p[1]) << 8)
                    | (static_cast<int32_t>(p[2]) << 16);
        if (val & 0x800000)
            val |= static_cast<int32_t>(~0xFFFFFF); /* sign-extend */
        sample[static_cast<size_t>(ch)] = static_cast<float>(val);
    }
    return sample;
}


/* ═══════════════════════════════════════════════════════════════════════════
 * LSLPublisher
 * ═══════════════════════════════════════════════════════════════════════════ */

LSLPublisher::LSLPublisher(const std::string& name,
                           const std::string& stream_type,
                           int                n_channels,
                           int                sample_rate,
                           const std::string& source_id)
{
    lsl_streaminfo info = lsl_create_streaminfo(
        name.c_str(), stream_type.c_str(),
        n_channels, static_cast<double>(sample_rate),
        cft_float32, source_id.c_str());
    outlet_ = lsl_create_outlet(info, 0, 360);
    lsl_destroy_streaminfo(info);
    printf("[LSLPublisher] Outlet '%s' (%s) created\n",
           name.c_str(), stream_type.c_str());
}

LSLPublisher::~LSLPublisher()
{
    if (outlet_)
        lsl_destroy_outlet(outlet_);
}

void LSLPublisher::push_sample(const std::vector<float>& sample)
{
    lsl_push_sample_f(outlet_, sample.data());
}


/* ═══════════════════════════════════════════════════════════════════════════
 * LSLConsumer
 * ═══════════════════════════════════════════════════════════════════════════ */

LSLConsumer::LSLConsumer(const std::string& stream_type)
{
    printf("[LSLConsumer] Resolving LSL stream of type '%s'...\n",
           stream_type.c_str());

    lsl_streaminfo results[1];
    int found = lsl_resolve_byprop(results, 1, "type", stream_type.c_str(), 0, 10.0);
    if (found < 1)
        throw std::runtime_error("LSLConsumer: could not resolve stream of type: " + stream_type);

    n_channels_ = lsl_get_channel_count(results[0]);
    inlet_      = lsl_create_inlet(results[0], 300, LSL_NO_PREFERENCE, 1);
    lsl_destroy_streaminfo(results[0]);
    printf("[LSLConsumer] Stream resolved (%d channels)\n", n_channels_);
}

LSLConsumer::~LSLConsumer()
{
    if (inlet_)
        lsl_destroy_inlet(inlet_);
}

std::pair<double, std::vector<float>> LSLConsumer::get_sample()
{
    std::vector<float> data(static_cast<size_t>(n_channels_));
    double ts = 0.0;
    int32_t ec = 0;
    lsl_pull_sample_f(inlet_, data.data(), n_channels_, LSL_FOREVER, &ec);
    return {ts, data};
}

std::pair<std::vector<double>, std::vector<std::vector<float>>>
LSLConsumer::get_chunk(int max_samples)
{
    const size_t buf_elems = static_cast<size_t>(max_samples * n_channels_);
    std::vector<float>  flat(buf_elems);
    std::vector<double> timestamps(static_cast<size_t>(max_samples));

    int32_t ec = 0;
    unsigned long pulled = lsl_pull_chunk_f(
        inlet_, flat.data(), timestamps.data(),
        buf_elems, static_cast<unsigned long>(max_samples),
        0.0, &ec);   /* timeout=0 → non-blocking */

    const int n = static_cast<int>(pulled);
    std::vector<std::vector<float>> samples(static_cast<size_t>(n));
    for (int s = 0; s < n; ++s) {
        samples[static_cast<size_t>(s)].resize(static_cast<size_t>(n_channels_));
        for (int ch = 0; ch < n_channels_; ++ch)
            samples[static_cast<size_t>(s)][static_cast<size_t>(ch)] =
                flat[static_cast<size_t>(s * n_channels_ + ch)];
    }

    timestamps.resize(static_cast<size_t>(n));
    return {timestamps, samples};
}


/* ═══════════════════════════════════════════════════════════════════════════
 * LSLBridge
 * ═══════════════════════════════════════════════════════════════════════════ */

LSLBridge::LSLBridge(TCPSource&           tcp,
                     BioSemi24BitDecoder& decoder,
                     LSLPublisher&        publisher)
    : tcp_(tcp), decoder_(decoder), publisher_(publisher) {}

void LSLBridge::start()
{
    tcp_.connect();   /* blocks until connected (mirrors Python) */
    thread_ = std::thread(stream_loop, &tcp_, &decoder_, &publisher_);
    thread_.detach(); /* daemon thread */
    printf("[LSLBridge] Streaming thread started\n");
}

/* static */
void LSLBridge::stream_loop(TCPSource*           tcp,
                            BioSemi24BitDecoder* decoder,
                            LSLPublisher*        publisher)
{
    const int block_sz = decoder->sample_block_size();
    std::vector<uint8_t> raw(static_cast<size_t>(block_sz));

    while (true) {
        if (tcp->recv_exact(raw.data(), block_sz) != 0) {
            fprintf(stderr, "[LSLBridge] TCP read error — exiting stream loop\n");
            break;
        }
        auto sample = decoder->decode_block(raw.data());
        publisher->push_sample(sample);
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
 * main — standalone binary entry point
 * ═══════════════════════════════════════════════════════════════════════════ */

static volatile bool g_running = true;
static void on_signal(int) { g_running = false; }

int main(int argc, char* argv[])
{
    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);

    const char* cfg_path = (argc > 1) ? argv[1] : "config/constants.json";
    NeuroRaveConfig cfg  = config_load(cfg_path);
    config_print(&cfg);

    if (cfg.simulate) {
        fprintf(stderr,
            "[neuro_lsl_bridge] SIMULATE=true — no hardware to bridge.\n");
        return 1;
    }

    TCPSource           tcp(cfg.biosemi_host, cfg.biosemi_port);
    BioSemi24BitDecoder decoder(cfg.n_channels);
    LSLPublisher        publisher("BioSemiEEG", "EEG",
                                  cfg.n_channels, cfg.sample_rate,
                                  "biosemi_tcp_bridge");
    LSLBridge bridge(tcp, decoder, publisher);
    bridge.start();

    printf("[neuro_lsl_bridge] Running — Ctrl-C to stop\n");
    while (g_running)
        std::this_thread::sleep_for(std::chrono::milliseconds(100));

    return 0;
}
