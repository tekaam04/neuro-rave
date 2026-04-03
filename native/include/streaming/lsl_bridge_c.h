#pragma once

/*
 * lsl_bridge_c.h — C structs mirroring src/streaming/lslbridge.py
 *
 * Naming convention: StructName_method(&self, ...)
 * maps directly to Python's   self.method(...)
 *
 * Structs:
 *   TCPSource            → lslbridge.py  TCPSource
 *   BioSemi24BitDecoder  → lslbridge.py  BioSemi24BitDecoder
 *   LSLPublisher         → lslbridge.py  LSLPublisher
 *   LSLConsumer          → lslbridge.py  LSLConsumer
 *   LSLBridge            → lslbridge.py  LSLBridge
 */

#include <lsl/lsl_c.h>
#include <pthread.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif


/* ── TCPSource ────────────────────────────────────────────────────────────── */

typedef struct {
    char host[64];
    int  port;
    int  sockfd;
} TCPSource;

/* TCPSource.__init__(host, port) */
void TCPSource_init(TCPSource *self, const char *host, int port);

/* TCPSource.connect() — blocks until connected, retries every 2 s */
void TCPSource_connect(TCPSource *self);

/* TCPSource.recv_exact(n_bytes) — fills buf; returns 0 on success, -1 on disconnect */
int  TCPSource_recv_exact(TCPSource *self, uint8_t *buf, int n_bytes);

/* Close the socket */
void TCPSource_destroy(TCPSource *self);


/* ── BioSemi24BitDecoder ──────────────────────────────────────────────────── */

typedef struct {
    int n_channels;
    int bytes_per_sample;    /* always 3 */
    int sample_block_size;   /* n_channels * 3 */
} BioSemi24BitDecoder;

/* BioSemi24BitDecoder.__init__(n_channels) */
void BioSemi24BitDecoder_init(BioSemi24BitDecoder *self, int n_channels);

/* BioSemi24BitDecoder.decode_block(raw_block)
 * raw must point to sample_block_size bytes.
 * out_sample must point to n_channels floats (caller allocates). */
void BioSemi24BitDecoder_decode_block(const BioSemi24BitDecoder *self,
                                      const uint8_t             *raw,
                                      float                     *out_sample);


/* ── LSLPublisher ─────────────────────────────────────────────────────────── */

typedef struct {
    lsl_outlet outlet;
} LSLPublisher;

/* LSLPublisher.__init__(name, type, n_channels, sample_rate, source_id) */
void LSLPublisher_init(LSLPublisher *self,
                       const char   *name,
                       const char   *stream_type,
                       int           n_channels,
                       int           sample_rate,
                       const char   *source_id);

/* LSLPublisher.push_sample(sample) — sample must have n_channels floats */
void LSLPublisher_push_sample(LSLPublisher *self, const float *sample);

void LSLPublisher_destroy(LSLPublisher *self);


/* ── LSLConsumer ──────────────────────────────────────────────────────────── */

typedef struct {
    lsl_inlet inlet;
    int       n_channels;
} LSLConsumer;

/* LSLConsumer.__init__(stream_type) — resolves the LSL stream (blocks up to 10 s) */
void LSLConsumer_init(LSLConsumer *self, const char *stream_type);

/* LSLConsumer.get_sample()
 * out_sample  — caller-allocated float[n_channels]
 * out_ts      — LSL timestamp
 * Returns 0 on success. */
int  LSLConsumer_get_sample(LSLConsumer *self, float *out_sample, double *out_ts);

/* LSLConsumer.get_chunk(max_samples)
 * out_samples_flat — caller-allocated float[max_samples * n_channels], row-major
 * out_timestamps   — caller-allocated double[max_samples]
 * Returns number of samples pulled (0 if none available). */
int  LSLConsumer_get_chunk(LSLConsumer *self,
                           float       *out_samples_flat,
                           double      *out_timestamps,
                           int          max_samples);

void LSLConsumer_destroy(LSLConsumer *self);


/* ── LSLBridge ────────────────────────────────────────────────────────────── */

typedef struct {
    TCPSource           *tcp;
    BioSemi24BitDecoder *decoder;
    LSLPublisher        *publisher;
    pthread_t            thread;
} LSLBridge;

/* LSLBridge.__init__(tcp, decoder, publisher) */
void LSLBridge_init(LSLBridge           *self,
                    TCPSource           *tcp,
                    BioSemi24BitDecoder *decoder,
                    LSLPublisher        *publisher);

/* LSLBridge.start() — connect TCP, then start streaming daemon thread */
void LSLBridge_start(LSLBridge *self);


#ifdef __cplusplus
}
#endif
