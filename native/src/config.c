/*
 * config.c — parse config/constants.json into a NeuroRaveConfig struct.
 *
 * Uses a simple line-by-line parser rather than a full JSON library.
 * constants.json is a flat object with no nested structures, so this is safe
 * and avoids any external dependencies.
 *
 * Mirrors: src/constants.py
 */

#include "config.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ── Default values (must match config/constants.json) ─────────────────────── */

static NeuroRaveConfig default_config(void)
{
    NeuroRaveConfig cfg;
    cfg.n_channels      = 8;
    cfg.sample_rate     = 512;
    cfg.window_size     = 512;
    cfg.simulate        = 0;
    cfg.biosemi_port    = 8888;
    cfg.bytes_per_sample = 3;
    cfg.ws_port         = 8733;
    strncpy(cfg.biosemi_host, "127.0.0.1", sizeof(cfg.biosemi_host) - 1);
    cfg.biosemi_host[sizeof(cfg.biosemi_host) - 1] = '\0';
    strncpy(cfg.ws_host, "0.0.0.0", sizeof(cfg.ws_host) - 1);
    cfg.ws_host[sizeof(cfg.ws_host) - 1] = '\0';
    return cfg;
}

/* ── Helpers ────────────────────────────────────────────────────────────────── */

/* Trim leading whitespace; returns pointer into the original string. */
static const char *ltrim(const char *s)
{
    while (*s && isspace((unsigned char)*s))
        s++;
    return s;
}

/*
 * Parse one line of the JSON object.
 * Expected format (with optional surrounding whitespace):
 *   "KEY": VALUE,
 * VALUE may be a quoted string, a number, or a boolean (true/false).
 */
static void parse_line(NeuroRaveConfig *cfg, const char *line)
{
    line = ltrim(line);
    if (*line != '"')
        return; /* skip { } and blank lines */

    /* Extract key */
    const char *key_start = line + 1;
    const char *key_end   = strchr(key_start, '"');
    if (!key_end)
        return;

    char key[64];
    int  key_len = (int)(key_end - key_start);
    if (key_len <= 0 || key_len >= (int)sizeof(key))
        return;
    strncpy(key, key_start, (size_t)key_len);
    key[key_len] = '\0';

    /* Advance past the colon */
    const char *colon = strchr(key_end + 1, ':');
    if (!colon)
        return;
    const char *val = ltrim(colon + 1);

    /* ── Integer fields ───────────────────────────────────────────────────── */
    if      (strcmp(key, "N_CHANNELS")       == 0) cfg->n_channels       = atoi(val);
    else if (strcmp(key, "SAMPLE_RATE")      == 0) cfg->sample_rate      = atoi(val);
    else if (strcmp(key, "WINDOW_SIZE")      == 0) cfg->window_size      = atoi(val);
    else if (strcmp(key, "BIOSEMI_PORT")     == 0) cfg->biosemi_port     = atoi(val);
    else if (strcmp(key, "BYTES_PER_SAMPLE") == 0) cfg->bytes_per_sample = atoi(val);
    else if (strcmp(key, "WS_PORT")          == 0) cfg->ws_port          = atoi(val);

    /* ── Boolean fields ───────────────────────────────────────────────────── */
    else if (strcmp(key, "SIMULATE") == 0)
        cfg->simulate = (strncmp(val, "true", 4) == 0) ? 1 : 0;

    /* ── String fields ────────────────────────────────────────────────────── */
    else if (strcmp(key, "BIOSEMI_HOST") == 0 || strcmp(key, "WS_HOST") == 0) {
        const char *vs = strchr(val, '"');
        if (!vs) return;
        vs++;
        const char *ve = strchr(vs, '"');
        if (!ve) return;
        int len = (int)(ve - vs);

        char *dest      = (strcmp(key, "BIOSEMI_HOST") == 0)
                          ? cfg->biosemi_host : cfg->ws_host;
        int   dest_size = (strcmp(key, "BIOSEMI_HOST") == 0)
                          ? (int)sizeof(cfg->biosemi_host)
                          : (int)sizeof(cfg->ws_host);

        if (len >= dest_size)
            len = dest_size - 1;
        strncpy(dest, vs, (size_t)len);
        dest[len] = '\0';
    }
}

/* ── Public API ─────────────────────────────────────────────────────────────── */

NeuroRaveConfig config_load(const char *json_path)
{
    NeuroRaveConfig cfg = default_config();

    FILE *f = fopen(json_path, "r");
    if (!f) {
        fprintf(stderr, "[config] Warning: could not open '%s' — using defaults.\n",
                json_path);
        return cfg;
    }

    char line[512];
    while (fgets(line, sizeof(line), f))
        parse_line(&cfg, line);

    fclose(f);
    return cfg;
}

void config_print(const NeuroRaveConfig *cfg)
{
    printf("[config] n_channels=%d  sample_rate=%d  window_size=%d\n",
           cfg->n_channels, cfg->sample_rate, cfg->window_size);
    printf("[config] simulate=%d\n", cfg->simulate);
    printf("[config] biosemi=%s:%d  bytes_per_sample=%d\n",
           cfg->biosemi_host, cfg->biosemi_port, cfg->bytes_per_sample);
    printf("[config] ws=%s:%d\n", cfg->ws_host, cfg->ws_port);
}
