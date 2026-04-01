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

**Simulation vs real EEG (Docker):** `docker-compose.yml` passes **`SIMULATE=${SIMULATE:-1}`** into the `neuro-rave` service, so **`docker compose up` defaults to simulated EEG** (no BioSemi TCP required). For **real hardware**, set **`SIMULATE=0`** (or **`false`**) in the project **`.env`** (Compose reads it for variable substitution) and ensure your TCP bridge is reachable from the container at **`BIOSEMI_HOST`** (default **`host.docker.internal`**) and **`BIOSEMI_PORT`** from `config/constants.json`.

The **dashboard** service runs **`npm install && npm run dev`** on startup so Linux-native Rollup/Vite deps populate the anonymous `node_modules` volume (the bind mount over `./dashboard` would otherwise hide image-built modules).

Spotify still needs **`SPOTIFY_REFRESH_TOKEN`** (and mood playlist URIs or `config/spotify_mood_mapping.json`) in `./.env`. Restart the stack after changing `.env`.

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

**2. Activate Spotify on a device**

Open the Spotify app and start playing any song.

**3. Fixed-mood demo**

```bash
docker compose run --rm \
  -e SPOTIFY_FIXED_MOOD=hype \
  -e SPOTIFY_FIXED_DURATION_S=60 \
  neuro-rave python scripts/spotify_fixed_mood_demo.py

docker compose run --rm \
  -e SPOTIFY_FIXED_MOOD=calm \
  -e SPOTIFY_FIXED_DURATION_S=60 \
  -e SPOTIFY_FIXED_TICK_S=1 \
  neuro-rave python scripts/spotify_fixed_mood_demo.py

docker compose run --rm \
  -e SPOTIFY_FIXED_MOOD=focus \
  -e SPOTIFY_FIXED_DURATION_S=60 \
  -e SPOTIFY_FIXED_TICK_S=1 \
  neuro-rave python scripts/spotify_fixed_mood_demo.py
```

**What happens:** The script starts the playlist for that mood and prints progress for 60 seconds.

#### 4) Docker demo — `main.py` with Spotify (optional tuning)

`docker compose up` already runs **`main.py`** with simulation by default. To run a one-off container with an explicit minimum time between playlist changes:

```bash
docker compose run --rm \
  -e SIMULATE=1 \
  -e SPOTIFY_MIN_SWITCH_S=60 \
  neuro-rave python main.py
```

What to expect:
- Logs show `SIMULATE=true` and per-window lines like `Theta/Beta=... | mood=...`.
- Spotify only changes context when the **mood bucket** changes **and** at least **`SPOTIFY_MIN_SWITCH_S`** seconds have passed since the last switch (default **60**). Lower it (e.g. `15`) for more responsive playlist changes.
- Keep a Spotify playback device active.

#### 5) Real EEG in Docker

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

Either nothing is listening on the host for the BioSemi TCP port (common if **`SIMULATE=0`** but no bridge is running), or the container can't reach the host. `docker-compose.yml` sets **`BIOSEMI_HOST=host.docker.internal`** for the latter. For demos without hardware, ensure **`SIMULATE=1`** in `.env` or rely on the compose default **`SIMULATE=${SIMULATE:-1}`**.

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
