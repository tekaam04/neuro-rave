/*
 * ws_server_c.c — C struct mirroring src/streaming/ws_server.py
 *
 * Struct: EEGWebSocketServer
 *
 * Usage (standalone binary — run from repo root):
 *   ./native/build/neuro_ws_server_c [path/to/constants.json]
 */

#include "ws_server_c.h"
#include "config.h"

#include <lsl/lsl_c.h>
#include <libwebsockets.h>

#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>


/* ── libwebsockets protocol callback ─────────────────────────────────────── */

/* Global pointer so the C callback can reach the server instance.
 * Single-threaded service loop means no race condition. */
static EEGWebSocketServer *g_ws_server = NULL;

static int lws_cb(struct lws               *wsi,
                  enum lws_callback_reasons reason,
                  void                     *user,
                  void                     *in,
                  size_t                    len)
{
    (void)user;
    if (g_ws_server)
        return EEGWebSocketServer_on_event(g_ws_server, wsi, reason, in, len);
    return 0;
}

static const struct lws_protocols g_protocols[] = {
    { "eeg-raw", lws_cb, 0, 0, 0, NULL, 0 },
    { NULL, NULL, 0, 0, 0, NULL, 0 }
};


/* ═══════════════════════════════════════════════════════════════════════════
 * EEGWebSocketServer helpers (private)
 * ═══════════════════════════════════════════════════════════════════════════ */

/* Resolve the LSL EEG stream — mirrors _raw_loop resolve portion */
static void resolve_lsl_stream(EEGWebSocketServer *self)
{
    printf("[EEGWebSocketServer] Resolving LSL EEG stream...\n");
    lsl_streaminfo results[1];
    int found = lsl_resolve_byprop(results, 1, "type", "EEG", 0, 10.0);
    if (found < 1) {
        fprintf(stderr, "[EEGWebSocketServer] Could not resolve LSL EEG stream\n");
        return;
    }
    self->n_channels = lsl_get_channel_count(results[0]);
    self->inlet      = lsl_create_inlet(results[0], 300, LSL_NO_PREFERENCE, 1);
    lsl_destroy_streaminfo(results[0]);

    /* Allocate sample buffer: n_channels * window_size floats */
    const int max_samples = 512;
    self->samples = malloc((size_t)(self->n_channels * max_samples) * sizeof(float));
    printf("[EEGWebSocketServer] LSL stream resolved (%d channels)\n",
           self->n_channels);
}

/* Pull a non-blocking LSL chunk — mirrors _raw_loop pull portion */
static int pull_chunk(EEGWebSocketServer *self)
{
    const int max_samples = 512;
    double    timestamps[512];
    int32_t   ec = 0;

    unsigned long pulled = lsl_pull_chunk_f(
        self->inlet,
        self->samples,
        timestamps,
        (unsigned long)(max_samples * self->n_channels),
        (unsigned long)max_samples,
        0.0,   /* non-blocking */
        &ec);

    if (pulled == 0)
        return 0;

    self->n_samples = (int)pulled;
    self->timestamp = timestamps[0];
    return self->n_samples;
}

/* Pre-format JSON from current samples — mirrors RawPacket.to_json() */
static void format_json(EEGWebSocketServer *self)
{
    /* Upper bound: header + n_ch * n_samp * 14 chars per float */
    size_t needed = 128 + (size_t)(self->n_channels * self->n_samples) * 14;
    if (needed > self->json_cap) {
        self->json_buf = realloc(self->json_buf, needed);
        self->json_cap = needed;
    }

    int   offset = 0;
    char *p      = self->json_buf;
    int   cap    = (int)self->json_cap;

    offset += snprintf(p + offset, (size_t)(cap - offset),
                       "{\"type\":\"raw\",\"timestamp\":%.6f,\"channels\":[",
                       self->timestamp);

    for (int ch = 0; ch < self->n_channels; ++ch) {
        if (ch > 0 && offset < cap) p[offset++] = ',';
        if (offset < cap)           p[offset++] = '[';

        for (int s = 0; s < self->n_samples; ++s) {
            if (s > 0 && offset < cap) p[offset++] = ',';
            offset += snprintf(p + offset, (size_t)(cap - offset),
                               "%.4g",
                               self->samples[s * self->n_channels + ch]);
        }
        if (offset < cap) p[offset++] = ']';
    }
    if (offset + 3 < cap) {
        p[offset++] = ']';
        p[offset++] = '}';
        p[offset]   = '\0';
    }
    self->json_len = (size_t)offset;
}

/* Trigger writeable for all clients — mirrors _broadcast() */
static void broadcast(EEGWebSocketServer *self)
{
    if (self->context)
        lws_callback_on_writable_all_protocol(self->context, &g_protocols[0]);
}

/* Blocking service loop (runs on daemon thread) — mirrors _raw_loop outer loop */
static void *service_thread(void *arg)
{
    EEGWebSocketServer *self = (EEGWebSocketServer *)arg;
    g_ws_server = self;

    struct lws_context_creation_info info;
    memset(&info, 0, sizeof(info));
    info.port      = self->port;
    info.iface     = self->host;
    info.protocols = g_protocols;
    info.options   = LWS_SERVER_OPTION_HTTP_HEADERS_SECURITY_BEST_PRACTICES_ENFORCE;

    self->context = lws_create_context(&info);
    if (!self->context) {
        fprintf(stderr, "[EEGWebSocketServer] lws_create_context failed\n");
        return NULL;
    }

    printf("[EEGWebSocketServer] Listening on %s:%d\n", self->host, self->port);

    while (1) {
        if (pull_chunk(self) > 0) {
            format_json(self);
            broadcast(self);
        }
        lws_service(self->context, 5); /* 5 ms poll */
    }
    return NULL;
}


/* ═══════════════════════════════════════════════════════════════════════════
 * Public API
 * ═══════════════════════════════════════════════════════════════════════════ */

/* EEGWebSocketServer.__init__(host, port) */
void EEGWebSocketServer_init(EEGWebSocketServer *self,
                              const char         *host,
                              int                 port)
{
    memset(self, 0, sizeof(*self));
    strncpy(self->host, host, sizeof(self->host) - 1);
    self->host[sizeof(self->host) - 1] = '\0';
    self->port = port;
}

/* EEGWebSocketServer.start() */
void EEGWebSocketServer_start(EEGWebSocketServer *self)
{
    resolve_lsl_stream(self);
    pthread_create(&self->thread, NULL, service_thread, self);
    pthread_detach(self->thread); /* daemon */
    printf("[EEGWebSocketServer] Started on ws://%s:%d/ws\n",
           self->host, self->port);
}

void EEGWebSocketServer_destroy(EEGWebSocketServer *self)
{
    if (self->context) { lws_context_destroy(self->context); self->context = NULL; }
    if (self->inlet)   { lsl_destroy_inlet(self->inlet);     self->inlet   = NULL; }
    free(self->samples);  self->samples  = NULL;
    free(self->json_buf); self->json_buf = NULL;
}

/* libwebsockets event handler — mirrors on_event / _ws_endpoint / _broadcast */
int EEGWebSocketServer_on_event(EEGWebSocketServer       *self,
                                 struct lws               *wsi,
                                 enum lws_callback_reasons reason,
                                 void *in, size_t len)
{
    (void)in; (void)len;
    switch (reason) {
    case LWS_CALLBACK_ESTABLISHED:
        printf("[EEGWebSocketServer] Client connected\n");
        lws_callback_on_writable(wsi);
        break;

    case LWS_CALLBACK_CLOSED:
        printf("[EEGWebSocketServer] Client disconnected\n");
        break;

    case LWS_CALLBACK_SERVER_WRITEABLE:
        if (self->json_len > 0) {
            /* lws_write requires LWS_PRE bytes of padding before the payload */
            size_t   total = LWS_PRE + self->json_len;
            uint8_t *buf   = malloc(total);
            if (buf) {
                memcpy(buf + LWS_PRE, self->json_buf, self->json_len);
                lws_write(wsi, buf + LWS_PRE, self->json_len, LWS_WRITE_TEXT);
                free(buf);
            }
        }
        break;

    default:
        break;
    }
    return 0;
}


/* ═══════════════════════════════════════════════════════════════════════════
 * main — standalone binary entry point
 * ═══════════════════════════════════════════════════════════════════════════ */

static volatile int g_running = 1;
static void on_signal(int s) { (void)s; g_running = 0; }

int main(int argc, char *argv[])
{
    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);

    const char *cfg_path = (argc > 1) ? argv[1] : "config/constants.json";
    NeuroRaveConfig cfg  = config_load(cfg_path);
    config_print(&cfg);

    EEGWebSocketServer server;
    EEGWebSocketServer_init(&server, cfg.ws_host, cfg.ws_port);
    EEGWebSocketServer_start(&server);

    printf("[neuro_ws_server_c] Running — Ctrl-C to stop\n");
    while (g_running) sleep(1);

    EEGWebSocketServer_destroy(&server);
    return 0;
}
