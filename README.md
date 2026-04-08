# NEURO-RAVE

**Real-time EEG-driven music generation system**

NEURO-RAVE streams EEG data from BioSemi hardware, processes neural features in
real time, and uses those features to drive live music generation via Spotify and
Suno.

---

## System Overview

```
BioSemi → ActiView (TCP) → LSL Bridge → LSL Stream → EEG Processor
                                                           ↓
                              Dashboard ← WebSocket ← Feature Extraction
                              Spotify / Suno ←────────────┘
```

---

## Project Structure

```
neuro-rave/
├── config/
│   ├── constants.json          # Single source of truth for all config
│   └── spotify_mood_mapping.json
├── src/
│   ├── api/                    # FastAPI REST endpoints (/spotify/*)
│   ├── music_gen/              # Spotify + Suno controllers
│   ├── processing/             # DSP, feature extraction, circular buffer
│   └── streaming/              # Python LSLBridge + WebSocket server
├── native/                     # C and C++ implementations
│   ├── CMakeLists.txt
│   ├── include/                # Headers (config.h, lsl_bridge*.h, ws_server*.h)
│   └── src/                    # C++ (.cpp) and C (.c) source files
├── dashboard/                  # React + Vite frontend
├── scripts/                    # Demo and utility scripts
├── Makefile                    # All run / build targets
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Environment Setup

### Option 1 — Makefile (local, recommended for development)

**Python environment (conda)**

```bash
make setup          # creates neuro-rave conda env + installs all deps
make run            # run main.py inside the conda env
make run-sim        # same (set "SIMULATE": true in config/constants.json first)
make dashboard      # start the React dev server
```

The conda env is created once and only reinstalled when `requirements.txt` changes.
To activate the env for interactive use:

```bash
conda activate neuro-rave
python main.py
```

**JavaScript environment**

```bash
make setup-js       # npm install in dashboard/
make dashboard      # npm run dev
```

### Option 2 — Docker

```bash
docker compose build
docker compose up
```

To stop: `docker compose down`

**Simulation vs real EEG (Docker):** `docker-compose.yml` passes **`SIMULATE=${SIMULATE:-0}`** into the `neuro-rave` service, so **`docker compose up` defaults to real EEG** (expects BioSemi TCP / LSL on the host). For **simulation** without hardware, set **`SIMULATE=1`** (or **`true`**) in the project **`.env`**. Ensure the TCP bridge is reachable from the container at **`BIOSEMI_HOST`** (default **`host.docker.internal`**) and **`BIOSEMI_PORT`** from `config/constants.json`.

The **dashboard** service runs **`npm install && npm run dev`** on startup so Linux-native Rollup/Vite deps populate the anonymous `node_modules` volume (the bind mount over `./dashboard` would otherwise hide image-built modules).

Spotify still needs **`SPOTIFY_REFRESH_TOKEN`** in `./.env`. **Default playback is *context* mode** (mood → your calm/focus/hype playlist or album URIs via `config/spotify_mood_mapping.json` / env). Restart the stack after changing `.env`.

### Running other scripts in the container

```bash
docker compose exec neuro-rave bash
docker compose run --rm neuro-rave python src/streaming/tcp_test.py
```

Source files are volume-mounted, so local edits are reflected immediately
without rebuilding.

---

## C / C++ Native Layer

The `native/` directory contains C and C++ implementations of the LSL bridge and
WebSocket server. These are **standalone binaries** — they run alongside Python
and share `config/constants.json` as the single source of truth.

### Prerequisites

```bash
# macOS
brew install labstreaminglayer/tap/lsl libwebsockets

# Linux (Debian/Ubuntu)
apt install libwebsockets-dev
# liblsl: download from https://github.com/sccn/liblsl/releases
```

### Build

```bash
make build-c                  # runs cmake + make in native/build/
make clean-c                  # remove build artifacts
```

Or directly with CMake:

```bash
cmake -B native/build native/
cmake --build native/build --parallel
```

### Binaries produced

| Binary | Language | Purpose |
|--------|----------|---------|
| `neuro_lsl_bridge` | C++ | BioSemi TCP → LSL outlet |
| `neuro_lsl_bridge_c` | C | BioSemi TCP → LSL outlet |
| `neuro_ws_server` | C++ | LSL inlet → WebSocket broadcast |
| `neuro_ws_server_c` | C | LSL inlet → WebSocket broadcast |

Run from the repo root so `config/constants.json` is found at the expected path:

```bash
./native/build/neuro_lsl_bridge           # C++ LSL bridge
./native/build/neuro_lsl_bridge_c         # C LSL bridge
./native/build/neuro_ws_server            # C++ WebSocket server
./native/build/neuro_ws_server_c          # C WebSocket server

# Pass a custom config path if needed:
./native/build/neuro_lsl_bridge path/to/constants.json
```

The C and C++ classes mirror the Python API exactly — see
[docs/dev-reference.md](docs/dev-reference.md) for the full cross-language
equivalents table.

---

## Configuration

All tuneable values live in **`config/constants.json`** — Python, C, and C++ all
read from this file at startup. Do not add a second source of truth.

Key fields:

| Field | Default | Description |
|-------|---------|-------------|
| `SIMULATE` | `false` | Use generated EEG instead of hardware |
| `BIOSEMI_HOST` | `"127.0.0.1"` | BioSemi TCP host |
| `BIOSEMI_PORT` | `8888` | BioSemi TCP port |
| `WS_PORT` | `8733` | WebSocket server port |
| `N_CHANNELS` | `8` | EEG channel count |
| `SAMPLE_RATE` | `512` | Hz |
| `FOCUS_THETA_BETA_LOW` | `0.10` | Mean θ/β at or below → focus score 1.0 (linear map) |
| `FOCUS_THETA_BETA_HIGH` | `0.42` | Mean θ/β at or above → focus score 0.0 |
| `SIM_PHASE_SECONDS` | `30` | Simulated EEG only: seconds per **calm → focus → hype** segment |

To run in simulation mode, set `"SIMULATE": true` in `constants.json`.

---

## Spotify Setup

**Requirements:** Spotify Premium + active playback device

**1. Get a refresh token (run once on your host machine)**

```bash
python get_spotify_refresh_token.py
```

This writes `SPOTIFY_REFRESH_TOKEN` to `.env`. Restart containers after changing
`.env`.

**2. Mood playlists (calm, focus, hype) — required for context mode**

Context mode maps EEG moods to Spotify **`spotify:playlist:`** or **`spotify:album:`** URIs. The app resolves them in this **order**: **`config/spotify_mood_mapping.json`** (if it defines all three moods), else **`.env`** **`SPOTIFY_PLAYLIST_CALM`**, **`SPOTIFY_PLAYLIST_FOCUS`**, **`SPOTIFY_PLAYLIST_HYPE`**, else the same keys in **`config/constants.json`**.

- **Get a URI:** in the Spotify app, open the playlist or album → **Share** → **Copy link**. The link contains an ID; convert to API form, e.g.  
  `https://open.spotify.com/playlist/63K1r9eNMihJJGQ9RE0RMo` → **`spotify:playlist:63K1r9eNMihJJGQ9RE0RMo`**.

**Option A — JSON (recommended)**  
Copy `config/spotify_mood_mapping.example.json` to **`config/spotify_mood_mapping.json`** and replace the placeholders. Each of **`calm`**, **`focus`**, and **`hype`** must be set (single URI string or JSON array of URIs for rotation). Optional **`deep_focus`**: same as `focus` if omitted.

**Option B — `.env` (Docker forwards these)**  

```env
SPOTIFY_PLAYLIST_CALM=spotify:playlist:YOUR_CALM_ID
SPOTIFY_PLAYLIST_FOCUS=spotify:playlist:YOUR_FOCUS_ID
SPOTIFY_PLAYLIST_HYPE=spotify:playlist:YOUR_HYPE_ID
```

Multiple URIs per mood: comma-separated (no spaces inside URIs), e.g. `spotify:playlist:AAA,spotify:playlist:BBB`.

**3. Activate Spotify on a device**

Open the Spotify app and start playing any song.

**Optional: single-track recommendations (EEG → Spotify audio targets)**

**Default is *context* mode** (`SPOTIFY_PLAYBACK_MODE=context` in Compose when unset): mood → fixed playlist/album URIs from step **2**. That path uses **`PUT /me/player/play`** and is what most people should use.

To try **recommendations** instead, add to **`.env`** (also forwarded by `docker-compose.yml`):

```env
SPOTIFY_PLAYBACK_MODE=recommendations
SPOTIFY_RECOMMENDATIONS_LIMIT=20
SPOTIFY_SEED_GENRES=electronic,ambient,chill,house,dance
SPOTIFY_MARKET=US
# Optional: SPOTIFY_TARGET_TEMPO_MIN=72  SPOTIFY_TARGET_TEMPO_MAX=148
```

Use [Spotify’s allowed `seed_genres` values](https://developer.spotify.com/documentation/web-api/reference/get-recommendations) (comma-separated, **max five**; lowercase hyphenated names only). Set **`SPOTIFY_MARKET`** to your **ISO 3166-1 alpha-2** country code (e.g. `US`, `GB`) so the catalog matches your account.

**Limitation:** Spotify’s **`GET /v1/recommendations`** often returns **404** or fails for **many newer or standard developer apps** (API access is restricted for some accounts). If recommendations never work, **stay on context mode**—playlists do not depend on that endpoint.

Each time the **mood bucket** changes (cooldown **`SPOTIFY_MIN_SWITCH_S`**; default **10** seconds, set **`0`** for immediate switches), recommendations mode maps smoothed **`energy`** and **`focus`** to `target_energy`, `target_valence`, and `target_tempo`, then plays a **random** track from the API response.

Other optional **`.env`** knobs: `SPOTIFY_TARGET_TEMPO_MIN`, `SPOTIFY_TARGET_TEMPO_MAX`, `SPOTIFY_RECOMMENDATIONS_LIMIT`.

**Track pool mode (no Recommendations API — continuous-ish single tracks)**

Use a **CSV** of tracks with **`track_id`**, **`energy`**, **`valence`**, **`tempo`** (BPM)—e.g. [TidyTuesday `spotify_songs.csv`](https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/2020-01-21/spotify_songs.csv). The app maps EEG (same **`target_energy` / `target_valence` / `target_tempo`** as recommendations) and picks a **near neighbor** in that 3D space, then **`PUT /me/player/play`** one track. Works when **`/recommendations`** is blocked.

1. Copy the CSV to **`config/track_pool.csv`** (see `config/track_pool.example.csv` for column needs), **or** set an absolute path.
2. **`.env` — essentials (same Spotify auth as §1):** you need **`SPOTIFY_REFRESH_TOKEN`** plus **`SPOTIFY_PLAYBACK_MODE=pool`**. Client ID/secret usually come from **`config/constants.json`** unless you override via **`.env`** / Compose (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`). **`SPOTIFY_DEVICE_ID`** helps if you hit “no active device” (see troubleshooting).

**Minimal example:**

```env
SPOTIFY_REFRESH_TOKEN=your_token_here
SPOTIFY_PLAYBACK_MODE=pool
```

**Optional pool tuning** (defaults exist in code; omit unless you want to change behavior):

```env
# SPOTIFY_TRACK_POOL_CSV=/app/config/track_pool.csv   # default: ./config/track_pool.csv
# SPOTIFY_POOL_MIN_INTERVAL_S=10                      # default 10; min 5s enforced in code
# SPOTIFY_POOL_TOP_K=8
# SPOTIFY_POOL_ON_MOOD_CHANGE_ONLY=0                  # 1 = only change track when voted mood changes
# SPOTIFY_POOL_HISTORY=24
# SPOTIFY_POOL_TEMPO_MIN=60   SPOTIFY_POOL_TEMPO_MAX=200
# SPOTIFY_POOL_WEIGHT_ENERGY=1  SPOTIFY_POOL_WEIGHT_VALENCE=1  SPOTIFY_POOL_WEIGHT_TEMPO=0.85
```

**`SPOTIFY_POOL_MIN_INTERVAL_S`:** minimum seconds between new track picks (default **10**); lower for more frequent changes (watch rate limits / UX). **`SPOTIFY_POOL_ON_MOOD_CHANGE_ONLY=1`:** only change tracks when the **voted mood** changes (see earlier Q&A: playback end is not auto-detected).

**Command-line mode (overrides `SPOTIFY_PLAYBACK_MODE` for this run)**

| Command | Spotify behavior |
|---------|------------------|
| `python main.py --spotify-playlist` | Mood → playlist/album (`context`) |
| `python main.py --spotify-recommendations` | Recommendations → one track (needs `SPOTIFY_SEED_GENRES`) |
| `python main.py --spotify-pool` | CSV track pool → nearest feature match (needs pool file) |
| `python main.py` | Uses **`SPOTIFY_PLAYBACK_MODE`** from `.env` / Compose (default **context**) |

Docker example: `docker compose run --rm -e ... neuro-rave python main.py --spotify-recommendations`

**Mood pipeline (playlist + recommendations)**

- **Features:** `energy` blends alpha-suppression min–max (longer history via **`SPOTIFY_ENERGY_HISTORY_MAX`**) with **gamma** arousal (**`SPOTIFY_GAMMA_AROUSAL_WEIGHT`**) and a slow EMA (**`SPOTIFY_ENERGY_SLOW_ALPHA`**, **`SPOTIFY_ENERGY_FAST_WEIGHT`**).
- **Stabilization:** EMA on energy/focus (**`SPOTIFY_MOOD_EMA_ALPHA`**), then majority vote over the last **`SPOTIFY_MOOD_VOTE_WINDOWS`** proposed moods; set **`SPOTIFY_MOOD_VOTE_OFF=1`** to disable voting.
- **Buckets:** `calm`, `deep_focus`, `focus`, `hype` (see `propose_mood` in `spotify_controller.py`). **`deep_focus`** uses the **focus** playlist URIs unless you add a `deep_focus` key to `config/spotify_mood_mapping.json`.

**4. Simulated EEG + Spotify (`main.py`)**

With **`SIMULATE=1`** in `.env`, **`docker compose up`** runs **`main.py`** with **simulated EEG** (see the Docker section above). The simulator **rotates** band-limited waveforms: **calm → focus → hype**, **`SIM_PHASE_SECONDS`** each (from `constants.json`, default 30), so moods and playlists should follow over time. **`SPOTIFY_MIN_SWITCH_S`** sets a **minimum delay** between Spotify context/recommendation switches (default **10** seconds; **`0`** = switch as soon as the voted mood changes).

```bash
docker compose run --rm -e SIMULATE=1 neuro-rave python main.py
```

What to expect:
- Logs show `SIM phase -> calm|focus|hype`, then `Theta/Beta=... | mood=...`.
- Keep a Spotify playback device active.

**5. Real EEG in Docker**

Set **`SIMULATE=0`** in `.env`, run your BioSemi TCP source on the host at the port in **`config/constants.json`**, and use **`docker compose up`**. The container connects to **`host.docker.internal`** by default.

## Conda (local development)

```bash
conda create -n neuro-rave python=3.11 -y
conda activate neuro-rave
pip install -r requirements.txt
python main.py
```

**`.env` for local runs:** `main.py` loads `./.env` **before** reading `config/constants.json`, so you can set **`SIMULATE=1`** or **`EEG_SIM=1`** there for simulation without prefixing the command. Use **`SIMULATE=0`** for real hardware (TCP server on **`BIOSEMI_HOST`/`BIOSEMI_PORT`**). Variables already set in your shell take precedence over `.env` (standard `python-dotenv` behavior).

#### Troubleshooting Spotify

| Error | Fix |
|-------|-----|
| Recommendations **404** / no tracks | Use **`SPOTIFY_PLAYBACK_MODE=pool`** with a labeled CSV, or **`context`** playlists |
| "Premium required" | Spotify Premium is required for playback control |
| "No active device found" | Open Spotify and start playing any song first |
| "User not registered" | Add your email in Spotify Developer Dashboard |

---

## Dependency Management

All dependencies are pinned and language-specific:

| Language | File | Install via |
|----------|------|-------------|
| Python | `requirements.txt` | `make setup` or `pip install -r requirements.txt` |
| JavaScript | `dashboard/package.json` | `make setup-js` or `npm install` |
| C / C++ | system libraries | `brew install` / `apt install` (see above) |

**Rules:**
- Pin all Python packages to exact versions in `requirements.txt`
- Do not install packages manually inside containers
- Do not mix local venvs with the conda env or Docker
- Rebuilding C binaries after a `constants.json` change is not required (config is read at runtime)
- Upgrading NumPy or MNE requires testing the full EEG pipeline

---

## Development Workflow

### Python changes
Edit files locally — no rebuild needed (Docker volume-mounts `src/`).

### C / C++ changes
```bash
make build-c
```

### Dependency changes
- Python: update `requirements.txt` → `make setup` (or `docker compose build`)
- JS: update `dashboard/package.json` → `make setup-js`
- C/C++: install system library → re-run `make build-c`

---

## FAQ

**`zsh: command not found: docker`**
Docker Desktop must be running. If the symlink is broken:
```bash
sudo ln -sf /Applications/Docker.app/Contents/Resources/bin/docker /usr/local/bin/docker
```

**`docker-credential-desktop: executable file not found`**
Remove `"credsStore": "desktop"` from `~/.docker/config.json`.

**`ModuleNotFoundError: No module named 'pylsl'`**
```bash
conda activate neuro-rave
python main.py
```

If you intend to run only in Docker, use `docker compose up` or `docker compose run --rm neuro-rave python main.py` instead, and rebuild after changing `requirements.txt`.

**`ConnectionRefused` when running in Docker**
`BIOSEMI_HOST` in `docker-compose.yml` is set to `host.docker.internal`. Make
sure Docker Desktop is up to date.

Either nothing is listening on the host for the BioSemi TCP port (Compose defaults **`SIMULATE=0`**), or the container can't reach the host. `docker-compose.yml` sets **`BIOSEMI_HOST=host.docker.internal`** for the latter. For demos without hardware, set **`SIMULATE=1`** in `.env`.

**C build: `Could not find LSL` or `Could not find libwebsockets`**
```bash
# macOS
brew install labstreaminglayer/tap/lsl libwebsockets

# Then re-run:
make build-c
```

**C build: headers not found after brew install**
Pass the prefix explicitly:
```bash
cmake -B native/build native/ \
  -DLSL_DIR=$(brew --prefix lsl)/lib/cmake/LSL \
  -DLWS_DIR=$(brew --prefix libwebsockets)/lib/cmake/libwebsockets
```

---

## Core Principle

Reproducibility > Convenience.

A stable neural streaming system is more important than quick local installs.
See [docs/dev-reference.md](docs/dev-reference.md) for the full package and
cross-language reference.
