# Dev Reference

Cross-language API reference and duplicated-code tracker for NEURO-RAVE.
Update this file whenever a component is changed or ported to another language.

---

## Configuration

`config/constants.json` is the single source of truth read by all language layers at startup.

| Layer | File | How |
|-------|------|-----|
| Python | `src/constants.py` | `json.loads(_config_path.read_text())` |
| C | `native/src/config.c` | `config_load("config/constants.json")` → `NeuroRaveConfig` struct |
| C++ | `native/src/config.c` | same `config_load()` via `extern "C"` in `native/include/config.h` |

`NeuroRaveConfig` fields (C/C++ struct — mirrors `src/constants.py` attributes):

```c
typedef struct {
    int  n_channels;        // N_CHANNELS
    int  sample_rate;       // SAMPLE_RATE
    int  window_size;       // WINDOW_SIZE
    int  simulate;          // SIMULATE
    char biosemi_host[64];  // BIOSEMI_HOST
    int  biosemi_port;      // BIOSEMI_PORT
    int  bytes_per_sample;  // BYTES_PER_SAMPLE
    char ws_host[64];       // WS_HOST
    int  ws_port;           // WS_PORT
} NeuroRaveConfig;
```

---

## Cross-Language Equivalents

Every component here exists in Python, C, and C++. When behaviour changes in one,
check whether the others need updating.

### TCPSource

Blocking TCP connection to BioSemi hardware with `recv_exact`.

| | Python | C | C++ |
|-|--------|---|-----|
| **File** | `src/streaming/lslbridge.py` | `native/src/lsl_bridge_c.c` | `native/src/lsl_bridge.cpp` |
| **Header** | — | `native/include/lsl_bridge_c.h` | `native/include/lsl_bridge.h` |
| **Init** | `TCPSource(host, port)` | `TCPSource_init(&self, host, port)` | `TCPSource(host, port)` |
| **Connect** | `self.connect()` | `TCPSource_connect(&self)` | `self.connect()` |
| **Read** | `self.recv_exact(n)` → `bytes` | `TCPSource_recv_exact(&self, buf, n)` → `int` | `self.recv_exact(buf, n)` → `int` |
| **Destroy** | GC | `TCPSource_destroy(&self)` | destructor |

Behaviour: blocks on connect, retries every 2 s. `recv_exact` loops until all bytes received or returns error on disconnect.

---

### BioSemi24BitDecoder

Decodes one sample block (N×3 bytes, 24-bit little-endian signed) into floats.

| | Python | C | C++ |
|-|--------|---|-----|
| **File** | `src/streaming/lslbridge.py` | `native/src/lsl_bridge_c.c` | `native/src/lsl_bridge.cpp` |
| **Init** | `BioSemi24BitDecoder(n_channels)` | `BioSemi24BitDecoder_init(&self, n_channels)` | `BioSemi24BitDecoder(n_channels)` |
| **Decode** | `self.decode_block(raw)` → `np.ndarray` | `BioSemi24BitDecoder_decode_block(&self, raw, out_float*)` | `self.decode_block(raw)` → `vector<float>` |
| **Block size** | `self.sample_block_size` | `self.sample_block_size` | `self.sample_block_size()` |

Decode logic is identical in all three: bytes 0-2 = ch0, 3-5 = ch1, …; sign-extend from bit 23.

---

### LSLPublisher

Wraps an LSL outlet and pushes one sample at a time.

| | Python | C | C++ |
|-|--------|---|-----|
| **File** | `src/streaming/lslbridge.py` | `native/src/lsl_bridge_c.c` | `native/src/lsl_bridge.cpp` |
| **Init** | `LSLPublisher(name, type, n_ch, rate, source_id)` | `LSLPublisher_init(&self, ...)` | `LSLPublisher(name, type, n_ch, rate, source_id)` |
| **Push** | `self.push_sample(np_array)` | `LSLPublisher_push_sample(&self, float*)` | `self.push_sample(vector<float>)` |
| **Destroy** | GC | `LSLPublisher_destroy(&self)` | destructor |

All create a `cft_float32` LSL outlet named `"BioSemiEEG"` with type `"EEG"`.

---

### LSLConsumer

Resolves an LSL stream by type and pulls samples/chunks.

| | Python | C | C++ |
|-|--------|---|-----|
| **File** | `src/streaming/lslbridge.py` | `native/src/lsl_bridge_c.c` | `native/src/lsl_bridge.cpp` |
| **Init** | `LSLConsumer(stream_type="EEG")` | `LSLConsumer_init(&self, stream_type)` | `LSLConsumer(stream_type)` |
| **Get sample** | `self.get_sample()` → `(sample, ts)` | `LSLConsumer_get_sample(&self, out_float*, out_ts*)` | `self.get_sample()` → `pair<double, vector<float>>` |
| **Get chunk** | `self.get_chunk(max=512)` → `(samples, ts)` | `LSLConsumer_get_chunk(&self, flat*, ts*, max)` → `int n_pulled` | `self.get_chunk(max)` → `pair<vector<double>, vector<vector<float>>>` |
| **Destroy** | GC | `LSLConsumer_destroy(&self)` | destructor |

`get_chunk` is non-blocking in all three (timeout = 0). Data layout from LSL is row-major `[s0_ch0, s0_ch1, ..., sN_chM]`.

---

### LSLBridge

Orchestrates TCPSource → BioSemi24BitDecoder → LSLPublisher on a daemon thread.

| | Python | C | C++ |
|-|--------|---|-----|
| **File** | `src/streaming/lslbridge.py` | `native/src/lsl_bridge_c.c` | `native/src/lsl_bridge.cpp` |
| **Init** | `LSLBridge(tcp, decoder, publisher)` | `LSLBridge_init(&self, tcp*, decoder*, publisher*)` | `LSLBridge(tcp, decoder, publisher)` |
| **Start** | `self.start()` | `LSLBridge_start(&self)` | `self.start()` |
| **Thread** | `threading.Thread(daemon=True)` | `pthread_create` + `pthread_detach` | `std::thread` + `detach()` |

`start()` always blocks to connect TCP first, then launches the loop thread — same in all three.

---

### EEGWebSocketServer

Resolves LSL EEG stream, runs a WebSocket server, broadcasts raw EEG chunks as JSON.

| | Python | C | C++ |
|-|--------|---|-----|
| **File** | `src/streaming/ws_server.py` | `native/src/ws_server_c.c` | `native/src/ws_server.cpp` |
| **Header** | — | `native/include/ws_server_c.h` | `native/include/ws_server.h` |
| **Init** | `EEGWebSocketServer(host, port)` | `EEGWebSocketServer_init(&self, host, port)` | `EEGWebSocketServer(host, port)` |
| **Start** | `self.start()` | `EEGWebSocketServer_start(&self)` | `self.start()` |
| **Resolve LSL** | `_raw_loop` (async) | `resolve_lsl_stream()` (static) | `resolve_lsl_stream()` |
| **Pull chunk** | `_raw_loop` pull section | `pull_chunk()` (static) | `pull_chunk()` |
| **Format JSON** | `RawPacket.to_json()` | `format_json()` (static) | `format_json()` |
| **Broadcast** | `_broadcast(payload)` | `broadcast()` → `lws_callback_on_writable_all_protocol` | `broadcast()` → `lws_callback_on_writable_all_protocol` |
| **WS callback** | `_ws_endpoint(websocket)` | `EEGWebSocketServer_on_event(...)` | `EEGWebSocketServer::on_event(...)` |
| **Thread** | `threading.Thread(daemon=True)` | `pthread_create` + `pthread_detach` | `std::thread` + `detach()` |
| **Service loop** | asyncio event loop | `lws_service(ctx, 5ms)` | `lws_service(ctx, 5ms)` |
| **Destroy** | GC | `EEGWebSocketServer_destroy(&self)` | destructor |

---

## RawPacket JSON Schema

All three `EEGWebSocketServer` implementations broadcast this exact format.
Defined in Python at `src/streaming/packets.py`.

```json
{
  "type":      "raw",
  "timestamp": 1234567.89,
  "channels":  [
    [ch0_s0, ch0_s1, ..., ch0_sN],
    [ch1_s0, ch1_s1, ..., ch1_sN]
  ]
}
```

Layout: **columnar** — one array per channel, each array contains all samples for that channel in time order.

---

## Calling Convention Across Languages

Same method name in all three; only call syntax changes:

| Python | C | C++ |
|--------|---|-----|
| `obj.method(args)` | `StructName_method(&obj, args)` | `obj.method(args)` |
| `obj.field` | `obj.field` | `obj.field()` (getter) or `obj.field_` |
| constructor | `StructName_init(&obj, args)` | `StructName(args)` |
| destructor (GC) | `StructName_destroy(&obj)` | `~StructName()` |

---

## Not Yet Ported

Components that exist only in Python — candidates for future C/C++ work.

| Component | Python location | Notes |
|-----------|----------------|-------|
| `EEGProcessor` (band filters + feature extraction) | `main.py` | `bandpass`, `notch`, `bandpower`, theta/beta ratio, alpha suppression |
| `MirrorCircleBuffer` | `src/processing/fifo.py` | Circular buffer with mirrored second half for zero-copy windowed reads |
| `features_to_spotify()` | `main.py` | Maps EEG features → `SpotifyNeuroFeatures` energy/focus |
| `propose_mood()` / `classify_mood()` | `src/music_gen/spotify_controller.py` | 2D buckets: `calm`, `deep_focus`, `focus`, `hype` from `(energy, focus, d_energy)`; `deep_focus` URIs fall back to `focus` |
| `MoodStabilizer` | `src/music_gen/spotify_controller.py` | EMA + optional majority vote (`SPOTIFY_MOOD_*` env) before Spotify switch |
| `SpotifyNeuroController` | `src/music_gen/spotify_controller.py` | Mood → playlist URI, throttled switching |
| `FeaturesPacket` broadcast | `src/streaming/ws_server.py` | Feature JSON over WebSocket (C/C++ WS server currently sends raw only) |
