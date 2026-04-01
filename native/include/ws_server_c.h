#pragma once

/*
 * ws_server_c.h — C struct mirroring src/streaming/ws_server.py
 *
 *   EEGWebSocketServer  →  ws_server.py  EEGWebSocketServer
 *
 * JSON schema broadcast (matches packets.py RawPacket):
 *   { "type": "raw", "timestamp": <f>, "channels": [[ch0…], [ch1…], …] }
 */

#include <lsl/lsl_c.h>
#include <libwebsockets.h>
#include <pthread.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── EEGWebSocketServer ───────────────────────────────────────────────────── */

typedef struct {
    /* Public fields (mirror Python self.host / self.port) */
    char host[64];
    int  port;

    /* LSL inlet */
    lsl_inlet inlet;
    int       n_channels;

    /* Latest EEG chunk */
    float  *samples;       /* flat: [s0_ch0, s0_ch1, ..., sN_chM] */
    double  timestamp;
    int     n_samples;

    /* Pre-formatted JSON for current chunk */
    char   *json_buf;
    size_t  json_len;
    size_t  json_cap;

    /* libwebsockets context */
    struct lws_context *context;

    /* Daemon thread */
    pthread_t thread;
} EEGWebSocketServer;

/* EEGWebSocketServer.__init__(host, port) */
void EEGWebSocketServer_init(EEGWebSocketServer *self,
                              const char         *host,
                              int                 port);

/* EEGWebSocketServer.start() — resolve LSL, then launch service loop in daemon thread */
void EEGWebSocketServer_start(EEGWebSocketServer *self);

void EEGWebSocketServer_destroy(EEGWebSocketServer *self);

/* Internal — called from the libwebsockets C callback (not for external use) */
int  EEGWebSocketServer_on_event(EEGWebSocketServer       *self,
                                  struct lws               *wsi,
                                  enum lws_callback_reasons reason,
                                  void *in, size_t len);

#ifdef __cplusplus
}
#endif
