#pragma once

/*
 * ws_server.h — C++ class mirroring src/streaming/ws_server.py
 *
 *   EEGWebSocketServer  →  ws_server.py  EEGWebSocketServer
 *
 * Resolves an LSL EEG stream, starts a libwebsockets server on ws_host:ws_port,
 * and broadcasts raw EEG chunks as JSON to every connected client.
 *
 * JSON schema (matches packets.py RawPacket):
 *   { "type": "raw", "timestamp": <f>, "channels": [[ch0…], [ch1…], …] }
 */

#include "lsl_bridge.h"   /* LSLConsumer */

#include <libwebsockets.h>
#include <lsl/lsl_c.h>

#include <atomic>
#include <string>
#include <thread>
#include <unordered_set>
#include <vector>


class EEGWebSocketServer {
public:
    /* Mirrors: EEGWebSocketServer.__init__(host, port) */
    EEGWebSocketServer(const std::string& host = "0.0.0.0", int port = 8733);
    ~EEGWebSocketServer();

    /* Resolve LSL stream, then launch the service loop in a daemon thread.
     * Mirrors: EEGWebSocketServer.start() */
    void start();

    /* libwebsockets callback — must be public so the C callback can reach it. */
    int on_event(struct lws* wsi, enum lws_callback_reasons reason,
                 void* user, void* in, size_t len);

private:
    std::string host_;
    int         port_;

    /* LSL state */
    lsl_inlet   inlet_     = nullptr;
    int         n_channels_ = 0;

    /* Latest EEG chunk (updated by service loop, read in writeable callback) */
    std::vector<float>  samples_;   /* flat: [s0_ch0, s0_ch1, ..., sN_chM] */
    double              timestamp_  = 0.0;
    int                 n_samples_  = 0;
    std::vector<char>   json_buf_;  /* pre-formatted JSON for current chunk  */

    /* libwebsockets context */
    struct lws_context* context_ = nullptr;

    /* Daemon thread */
    std::thread thread_;

    /* ── Private methods (mirror Python private methods) ─────────────────── */

    /* Resolve the LSL EEG stream inlet.
     * Mirrors: EEGWebSocketServer._raw_loop (LSL resolve portion) */
    void resolve_lsl_stream();

    /* Pull a non-blocking LSL chunk into samples_ / timestamp_.
     * Returns number of samples pulled.
     * Mirrors: EEGWebSocketServer._raw_loop (pull portion) */
    int pull_chunk();

    /* Broadcast the current json_buf_ to all connected clients.
     * Mirrors: EEGWebSocketServer._broadcast */
    void broadcast();

    /* Pre-format json_buf_ from the current samples_ snapshot.
     * Mirrors: the RawPacket serialisation in _raw_loop */
    void format_json();

    /* Blocking service loop — runs on the daemon thread.
     * Mirrors: EEGWebSocketServer._raw_loop (outer loop) */
    void run();
};
