/*
 * ws_server.cpp — C++ class mirroring src/streaming/ws_server.py
 *
 * Class implemented here:
 *   EEGWebSocketServer
 *
 * Usage (standalone binary — run from repo root):
 *   ./native/build/neuro_ws_server [path/to/constants.json]
 */

#include "ws_server.h"
#include "config.h"
#include "lsl_bridge.h"

#include <libwebsockets.h>
#include <lsl/lsl_c.h>

#include <atomic>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <signal.h>
#include <stdexcept>
#include <thread>
#include <unistd.h>
#include <vector>


/* ── libwebsockets protocol callback (free function, calls into class) ─────── */

static EEGWebSocketServer* g_server = nullptr; /* set in EEGWebSocketServer::run() */

static int lws_callback(struct lws*               wsi,
                        enum lws_callback_reasons reason,
                        void*                     user,
                        void*                     in,
                        size_t                    len)
{
    if (g_server)
        return g_server->on_event(wsi, reason, user, in, len);
    return 0;
}

static const struct lws_protocols g_protocols[] = {
    { "eeg-raw", lws_callback, 0, 0, 0, nullptr, 0 },
    LWS_PROTOCOL_LIST_TERM
};


/* ═══════════════════════════════════════════════════════════════════════════
 * EEGWebSocketServer
 * ═══════════════════════════════════════════════════════════════════════════ */

EEGWebSocketServer::EEGWebSocketServer(const std::string& host, int port)
    : host_(host), port_(port) {}

EEGWebSocketServer::~EEGWebSocketServer()
{
    if (context_)
        lws_context_destroy(context_);
    if (inlet_)
        lsl_destroy_inlet(inlet_);
}

/* ── start() ─────────────────────────────────────────────────────────────── */

void EEGWebSocketServer::start()
{
    resolve_lsl_stream();

    /* Pre-allocate sample buffer */
    samples_.resize(static_cast<size_t>(n_channels_ * 8192)); /* max 8192 samples */

    thread_ = std::thread([this]() { run(); });
    thread_.detach(); /* daemon thread */

    printf("[EEGWebSocketServer] Started on ws://%s:%d/ws\n",
           host_.c_str(), port_);
}

/* ── resolve_lsl_stream() ───────────────────────────────────────────────────
 * Mirrors: EEGWebSocketServer._raw_loop (LSL resolve) */

void EEGWebSocketServer::resolve_lsl_stream()
{
    printf("[EEGWebSocketServer] Resolving LSL EEG stream...\n");
    lsl_streaminfo results[1];
    int found = lsl_resolve_byprop(results, 1, "type", "EEG", 0, 10.0);
    if (found < 1)
        throw std::runtime_error("EEGWebSocketServer: could not resolve LSL EEG stream");

    n_channels_ = lsl_get_channel_count(results[0]);
    inlet_      = lsl_create_inlet(results[0], 300, LSL_NO_PREFERENCE, 1);
    lsl_destroy_streaminfo(results[0]);
    printf("[EEGWebSocketServer] LSL stream resolved (%d channels)\n", n_channels_);
}

/* ── pull_chunk() ───────────────────────────────────────────────────────────
 * Mirrors: EEGWebSocketServer._raw_loop (pull + broadcast portion) */

int EEGWebSocketServer::pull_chunk()
{
    const int   max_samples = 512;
    const size_t buf_elems  = static_cast<size_t>(max_samples * n_channels_);

    std::vector<float>  flat(buf_elems);
    std::vector<double> ts(static_cast<size_t>(max_samples));

    int32_t ec = 0;
    unsigned long pulled = lsl_pull_chunk_f(
        inlet_, flat.data(), ts.data(),
        buf_elems, static_cast<unsigned long>(max_samples),
        0.0, &ec);

    if (pulled == 0)
        return 0;

    n_samples_ = static_cast<int>(pulled);
    timestamp_ = ts[0];

    /* Copy flat data into samples_ */
    samples_.resize(static_cast<size_t>(n_samples_ * n_channels_));
    std::copy(flat.begin(), flat.begin() + n_samples_ * n_channels_, samples_.begin());

    return n_samples_;
}

/* ── format_json() ──────────────────────────────────────────────────────────
 * Serialises the current chunk as a RawPacket JSON string.
 * Mirrors: packets.py RawPacket.to_json() */

void EEGWebSocketServer::format_json()
{
    /* Upper bound: header + n_channels * n_samples * 14 chars per float */
    size_t cap = 128 + static_cast<size_t>(n_channels_ * n_samples_) * 14;
    json_buf_.resize(cap);

    int offset = 0;
    auto append = [&](const char* fmt, auto... args) {
        int written = snprintf(json_buf_.data() + offset,
                               cap - static_cast<size_t>(offset), fmt, args...);
        if (written > 0) offset += written;
    };

    append("{\"type\":\"raw\",\"timestamp\":%.6f,\"channels\":[", timestamp_);

    for (int ch = 0; ch < n_channels_; ++ch) {
        if (ch > 0 && offset < static_cast<int>(cap)) json_buf_[offset++] = ',';
        if (offset < static_cast<int>(cap))            json_buf_[offset++] = '[';

        for (int s = 0; s < n_samples_; ++s) {
            if (s > 0 && offset < static_cast<int>(cap)) json_buf_[offset++] = ',';
            int written = snprintf(json_buf_.data() + offset,
                                   cap - static_cast<size_t>(offset),
                                   "%.4g",
                                   samples_[static_cast<size_t>(s * n_channels_ + ch)]);
            if (written > 0) offset += written;
        }
        if (offset < static_cast<int>(cap)) json_buf_[offset++] = ']';
    }
    if (offset + 3 < static_cast<int>(cap)) {
        json_buf_[offset++] = ']';
        json_buf_[offset++] = '}';
        json_buf_[offset]   = '\0';
    }
    json_buf_.resize(static_cast<size_t>(offset));
}

/* ── broadcast() ────────────────────────────────────────────────────────────
 * Triggers LWS_CALLBACK_SERVER_WRITEABLE for all connected clients.
 * Mirrors: EEGWebSocketServer._broadcast() */

void EEGWebSocketServer::broadcast()
{
    if (context_)
        lws_callback_on_writable_all_protocol(context_, &g_protocols[0]);
}

/* ── on_event() — libwebsockets callback ─────────────────────────────────── */

int EEGWebSocketServer::on_event(struct lws*               wsi,
                                 enum lws_callback_reasons reason,
                                 void* /*user*/,
                                 void* /*in*/,
                                 size_t /*len*/)
{
    switch (reason) {
    case LWS_CALLBACK_ESTABLISHED:
        printf("[EEGWebSocketServer] Client connected\n");
        lws_callback_on_writable(wsi);
        break;

    case LWS_CALLBACK_CLOSED:
        printf("[EEGWebSocketServer] Client disconnected\n");
        break;

    case LWS_CALLBACK_SERVER_WRITEABLE:
        if (!json_buf_.empty()) {
            /* lws_write requires LWS_PRE bytes of padding before the payload */
            size_t payload_len = json_buf_.size();
            std::vector<unsigned char> send_buf(LWS_PRE + payload_len);
            std::memcpy(send_buf.data() + LWS_PRE,
                        json_buf_.data(), payload_len);
            lws_write(wsi,
                      send_buf.data() + LWS_PRE,
                      payload_len,
                      LWS_WRITE_TEXT);
        }
        break;

    default:
        break;
    }
    return 0;
}

/* ── run() — blocking service loop (daemon thread) ──────────────────────────
 * Mirrors: EEGWebSocketServer._raw_loop (service loop) */

void EEGWebSocketServer::run()
{
    g_server = this;

    struct lws_context_creation_info info{};
    info.port      = port_;
    info.iface     = host_.c_str();
    info.protocols = g_protocols;
    info.options   = LWS_SERVER_OPTION_HTTP_HEADERS_SECURITY_BEST_PRACTICES_ENFORCE;

    context_ = lws_create_context(&info);
    if (!context_) {
        fprintf(stderr, "[EEGWebSocketServer] lws_create_context failed\n");
        return;
    }

    printf("[EEGWebSocketServer] Listening on %s:%d\n", host_.c_str(), port_);

    /* Service loop: pull LSL → format JSON → trigger writeable */
    while (true) {
        int pulled = pull_chunk();
        if (pulled > 0) {
            format_json();
            broadcast();
        }
        lws_service(context_, 5); /* 5 ms poll interval */
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

    EEGWebSocketServer server(cfg.ws_host, cfg.ws_port);
    server.start();

    printf("[neuro_ws_server] Running — Ctrl-C to stop\n");
    while (g_running)
        std::this_thread::sleep_for(std::chrono::milliseconds(100));

    return 0;
}
