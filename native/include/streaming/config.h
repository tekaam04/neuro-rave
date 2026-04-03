#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/*
 * NeuroRaveConfig — mirrors the fields in config/constants.json.
 *
 * Call config_load("config/constants.json") from the repo root to populate.
 * All fields are pre-filled with the same defaults as constants.json so the
 * binary is usable even if the file cannot be opened.
 */
typedef struct {
    /* Signal processing */
    int    n_channels;
    int    sample_rate;
    int    window_size;

    /* Mode */
    int    simulate;          /* 0 = real hardware, 1 = simulation */

    /* BioSemi hardware */
    char   biosemi_host[64];
    int    biosemi_port;
    int    bytes_per_sample;

    /* WebSocket server */
    char   ws_host[64];
    int    ws_port;
} NeuroRaveConfig;

/*
 * Parse config/constants.json and return a populated NeuroRaveConfig.
 * Falls back to compile-time defaults if the file cannot be opened.
 *
 * @param json_path  Path to constants.json, e.g. "config/constants.json"
 *                   (relative to the working directory when the binary runs).
 */
NeuroRaveConfig config_load(const char *json_path);

/* Print all fields to stdout (for debugging). */
void config_print(const NeuroRaveConfig *cfg);

#ifdef __cplusplus
}
#endif
