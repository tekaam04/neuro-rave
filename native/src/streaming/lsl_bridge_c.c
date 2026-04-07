/*
 * lsl_bridge_c.c — C structs mirroring src/streaming/lslbridge.py
 *
 * Structs: TCPSource, BioSemi24BitDecoder, LSLPublisher, LSLConsumer, LSLBridge
 *
 * Usage (standalone binary — run from repo root):
 *   ./native/build/neuro_lsl_bridge_c [path/to/constants.json]
 */

#include "lsl_bridge_c.h"
#include "config.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>


/* ═══════════════════════════════════════════════════════════════════════════
 * TCPSource
 * ═══════════════════════════════════════════════════════════════════════════ */

void TCPSource_init(TCPSource *self, const char *host, int port)
{
    strncpy(self->host, host, sizeof(self->host) - 1);
    self->host[sizeof(self->host) - 1] = '\0';
    self->port   = port;
    self->sockfd = -1;
}

void TCPSource_connect(TCPSource *self)
{
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port   = htons((uint16_t)self->port);

    if (inet_pton(AF_INET, self->host, &addr.sin_addr) != 1) {
        fprintf(stderr, "[TCPSource] Invalid host: %s\n", self->host);
        return;
    }

    while (1) {
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) { perror("[TCPSource] socket"); return; }

        if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
            self->sockfd = fd;
            printf("[TCPSource] Connected to %s:%d\n", self->host, self->port);
            return;
        }
        fprintf(stderr, "[TCPSource] Cannot connect to %s:%d: %s — retry in 2s\n",
                self->host, self->port, strerror(errno));
        close(fd);
        sleep(2);
    }
}

int TCPSource_recv_exact(TCPSource *self, uint8_t *buf, int n_bytes)
{
    int received = 0;
    while (received < n_bytes) {
        int r = (int)recv(self->sockfd, buf + received,
                          (size_t)(n_bytes - received), 0);
        if (r <= 0) return -1;
        received += r;
    }
    return 0;
}

void TCPSource_destroy(TCPSource *self)
{
    if (self->sockfd >= 0) {
        close(self->sockfd);
        self->sockfd = -1;
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
 * BioSemi24BitDecoder
 * ═══════════════════════════════════════════════════════════════════════════ */

void BioSemi24BitDecoder_init(BioSemi24BitDecoder *self, int n_channels)
{
    self->n_channels       = n_channels;
    self->bytes_per_sample = 3;
    self->sample_block_size = n_channels * 3;
}

void BioSemi24BitDecoder_decode_block(const BioSemi24BitDecoder *self,
                                      const uint8_t             *raw,
                                      float                     *out_sample)
{
    for (int ch = 0; ch < self->n_channels; ++ch) {
        const uint8_t *p = raw + ch * 3;
        int32_t val = (int32_t)p[0]
                    | ((int32_t)p[1] << 8)
                    | ((int32_t)p[2] << 16);
        /* Sign-extend from 24 bits */
        if (val & 0x800000)
            val |= (int32_t)~0xFFFFFF;
        out_sample[ch] = (float)val;
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
 * LSLPublisher
 * ═══════════════════════════════════════════════════════════════════════════ */

void LSLPublisher_init(LSLPublisher *self,
                       const char   *name,
                       const char   *stream_type,
                       int           n_channels,
                       int           sample_rate,
                       const char   *source_id)
{
    lsl_streaminfo info = lsl_create_streaminfo(
        name, stream_type, n_channels, (double)sample_rate,
        cft_float32, source_id);
    self->outlet = lsl_create_outlet(info, 0, 360);
    lsl_destroy_streaminfo(info);
    printf("[LSLPublisher] Outlet '%s' (%s) created\n", name, stream_type);
}

void LSLPublisher_push_sample(LSLPublisher *self, const float *sample)
{
    lsl_push_sample_f(self->outlet, sample);
}

void LSLPublisher_destroy(LSLPublisher *self)
{
    if (self->outlet) {
        lsl_destroy_outlet(self->outlet);
        self->outlet = NULL;
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
 * LSLConsumer
 * ═══════════════════════════════════════════════════════════════════════════ */

void LSLConsumer_init(LSLConsumer *self, const char *stream_type)
{
    printf("[LSLConsumer] Resolving LSL stream of type '%s'...\n", stream_type);
    lsl_streaminfo results[1];
    int found = lsl_resolve_byprop(results, 1, "type", stream_type, 0, 10.0);
    if (found < 1) {
        fprintf(stderr, "[LSLConsumer] Could not resolve stream of type '%s'\n",
                stream_type);
        self->inlet      = NULL;
        self->n_channels = 0;
        return;
    }
    self->n_channels = lsl_get_channel_count(results[0]);
    self->inlet      = lsl_create_inlet(results[0], 300, LSL_NO_PREFERENCE, 1);
    lsl_destroy_streaminfo(results[0]);
    printf("[LSLConsumer] Stream resolved (%d channels)\n", self->n_channels);
}

int LSLConsumer_get_sample(LSLConsumer *self, float *out_sample, double *out_ts)
{
    int32_t ec = 0;
    *out_ts = lsl_pull_sample_f(self->inlet, out_sample, self->n_channels,
                                 LSL_FOREVER, &ec);
    return (ec == 0) ? 0 : -1;
}

int LSLConsumer_get_chunk(LSLConsumer *self,
                          float       *out_samples_flat,
                          double      *out_timestamps,
                          int          max_samples)
{
    int32_t ec = 0;
    unsigned long pulled = lsl_pull_chunk_f(
        self->inlet,
        out_samples_flat,
        out_timestamps,
        (unsigned long)(max_samples * self->n_channels),
        (unsigned long)max_samples,
        0.0,   /* timeout = 0 → non-blocking */
        &ec);
    return (int)pulled;
}

void LSLConsumer_destroy(LSLConsumer *self)
{
    if (self->inlet) {
        lsl_destroy_inlet(self->inlet);
        self->inlet = NULL;
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
 * LSLBridge
 * ═══════════════════════════════════════════════════════════════════════════ */

static void *stream_loop(void *arg)
{
    LSLBridge *self = (LSLBridge *)arg;
    const int  block_sz = self->decoder->sample_block_size;
    uint8_t   *raw    = malloc((size_t)block_sz);
    float     *sample = malloc((size_t)self->decoder->n_channels * sizeof(float));

    if (!raw || !sample) {
        fprintf(stderr, "[LSLBridge] Out of memory\n");
        free(raw);
        free(sample);
        return NULL;
    }

    while (1) {
        if (TCPSource_recv_exact(self->tcp, raw, block_sz) != 0) {
            fprintf(stderr, "[LSLBridge] TCP read error — exiting stream loop\n");
            break;
        }
        BioSemi24BitDecoder_decode_block(self->decoder, raw, sample);
        LSLPublisher_push_sample(self->publisher, sample);
    }

    free(raw);
    free(sample);
    return NULL;
}

void LSLBridge_init(LSLBridge           *self,
                    TCPSource           *tcp,
                    BioSemi24BitDecoder *decoder,
                    LSLPublisher        *publisher)
{
    self->tcp       = tcp;
    self->decoder   = decoder;
    self->publisher = publisher;
}

void LSLBridge_start(LSLBridge *self)
{
    TCPSource_connect(self->tcp);   /* mirrors Python: blocks until connected */
    pthread_create(&self->thread, NULL, stream_loop, self);
    pthread_detach(self->thread);   /* daemon thread */
    printf("[LSLBridge] Streaming thread started\n");
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

    if (cfg.simulate) {
        fprintf(stderr,
            "[neuro_lsl_bridge_c] SIMULATE=true — no hardware to bridge.\n");
        return 1;
    }

    TCPSource           tcp;
    BioSemi24BitDecoder decoder;
    LSLPublisher        publisher;
    LSLBridge           bridge;

    TCPSource_init(&tcp, cfg.biosemi_host, cfg.biosemi_port);
    BioSemi24BitDecoder_init(&decoder, cfg.n_channels);
    LSLPublisher_init(&publisher,
                      "BioSemiEEG", "EEG",
                      cfg.n_channels, cfg.sample_rate,
                      "biosemi_tcp_bridge");
    LSLBridge_init(&bridge, &tcp, &decoder, &publisher);
    LSLBridge_start(&bridge);

    printf("[neuro_lsl_bridge_c] Running — Ctrl-C to stop\n");
    while (g_running) sleep(1);

    LSLPublisher_destroy(&publisher);
    TCPSource_destroy(&tcp);
    return 0;
}
