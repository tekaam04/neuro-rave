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
# macOS: start stack, open dashboard in browser, tail logs (preferred for demos)
make compose-up-open
# or, without auto-opening the browser:
docker compose up
```

To stop: `docker compose stop`

**Simulation vs real EEG (Docker):** `docker-compose.yml` passes **`SIMULATE=${SIMULATE:-0}`** into the `neuro-rave` service, so **`docker compose up` defaults to real EEG** (expects BioSemi TCP / LSL on the host). For **simulation** without hardware, set **`SIMULATE=1`** (or **`true`**) in the project **`.env`**. Ensure the TCP bridge is reachable from the container at **`BIOSEMI_HOST`** (default **`host.docker.internal`**) and **`BIOSEMI_PORT`** from `config/constants.json`.

The **dashboard** service runs **`npm install && npm run dev`** on startup so Linux-native Rollup/Vite deps populate the anonymous `node_modules` volume (the bind mount over `./dashboard` would otherwise hide image-built modules).

Spotify auth can now come from the dashboard setup flow: **Connect Spotify** stores a local refresh token at `config/.spotify_refresh_token` (gitignored). You can still set **`SPOTIFY_REFRESH_TOKEN`** in `./.env` for manual/CI runs; if set, env takes precedence. **Default playback is *context* mode** (mood → your calm/focus/hype playlist or album URIs via `config/spotify_mood_mapping.json` / env).

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

**Requirements:** Spotify **Premium** and a **playback device** (phone, desktop, etc.).

---

### For users (simple path)

Use this when the project already has a working Spotify app configured (someone set **Client ID**, **secret**, and **redirect URI** in the developer dashboard).

1. **Start the app**  
   - **macOS + Docker:** from the repo root run **`make compose-up-open`** — starts Compose, opens **`http://127.0.0.1:5173`**, and tails logs.  
   - **Otherwise:** **`docker compose up`**, or **`make run`** plus **`make dashboard`** in two terminals.

2. **Connect your account**  
   Open **`http://127.0.0.1:5173/setup`** (or **Connect Spotify** on the home dashboard). Finish the browser login. Your refresh token is saved to **`config/.spotify_refresh_token`** (gitignored). If **`SPOTIFY_REFRESH_TOKEN`** is in **`.env`**, that overrides the file.

3. **Pick music per mood**  
   Choose playlists from the list **or paste** **Share → Copy link** URLs (no manual `spotify:playlist:…` conversion on this page). **Multiple playlists per mood:** comma-separated links in one field. **Save** writes **`config/spotify_mood_mapping.json`**; **`main.py`** reloads without restart; in **playlist** mode, Save may start **calm** if a device is ready.

4. **Wake a device**  
   Open Spotify and press **Play** once so playback control can attach.

On **`/`**, **Playlist mode** vs **Pool mode** changes how tracks are chosen, and **Update playlist** opens **`/setup`** to edit mapping. Mode toggles do not navigate away. The active mode is stored in **`config/dashboard_spotify_playback_mode.json`**.
The dashboard also includes **Now playing** info and **Pause/Resume playback**. While paused, neuro-driven track/context switching is locked (persisted at **`config/dashboard_spotify_pause_state.json`**).

If **Connect Spotify** fails (redirect / **HTTP 400** / “not configured”), a **developer** must fix the Spotify app — see **For developers** below.

---

### For developers (Spotify app, secrets, URLs)

**1. Spotify Developer app**

- In the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard), open your app → **Settings**.
- **Redirect URIs:** add the **exact** callback the backend uses. With default **`WS_PORT=8733`**:  
  **`http://127.0.0.1:8733/spotify/oauth/callback`**  
  The **Setup** page lists the precise string for your run — use that if it differs (custom port or **`SPOTIFY_OAUTH_REDIRECT_URI`**). **`localhost` and `127.0.0.1` are not interchangeable** for Spotify.
- Add **test users** / emails if the app is in development mode.

**2. Client ID and Client Secret**

Change these when you use **your own** Spotify app or a new fork:

| Location | Purpose |
|----------|---------|
| **`config/constants.json`** | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` — team defaults; **never commit real secrets** to a public repository. |
| **`.env`** | Same variable names; loaded **before** `constants.json`, so this **overrides** JSON. Prefer this for local secrets. |
| **Host env + Compose** | `docker-compose.yml` passes `${SPOTIFY_CLIENT_ID}` / `${SPOTIFY_CLIENT_SECRET}` into the container — set them in your shell or `.env` at the project root. |

**3. API port and OAuth**

- OAuth callback and REST live on **`WS_PORT`** (see `config/constants.json`, default **8733**).
- OAuth success redirect defaults to **`http://localhost:5173/`** (home dashboard) via **`SPOTIFY_OAUTH_SUCCESS_URL`**.
- Flow uses **PKCE**. Persistent **HTTP 400** on login: see [Spotify OAuth migration](https://developer.spotify.com/blog/2025-10-14-reminder-oauth-migration-27-nov-2025); you may need **HTTPS** (e.g. ngrok), register that URL in Spotify, and align **`SPOTIFY_OAUTH_REDIRECT_URI`** / **`SPOTIFY_OAUTH_PUBLIC_HOST`** (see **`docker-compose.yml`** comments).

**4. Playlist source precedence (playlist / context mode)**

1. **`config/spotify_mood_mapping.json`** if **calm**, **focus**, and **hype** are all set  
2. Else **`SPOTIFY_PLAYLIST_*`** in **`.env`**  
3. Else **`config/constants.json`**

**5. CLI token helper (optional)**

```bash
python get_spotify_refresh_token.py
```

Writes **`.env`** and **`config/.spotify_refresh_token`** if you skip the dashboard.

**6. Edit mapping without the dashboard**

- **JSON:** `config/spotify_mood_mapping.json` — **`calm`**, **`focus`**, **`hype`** as `spotify:playlist:` / `spotify:album:` strings or arrays; optional **`deep_focus`**. On-disk JSON must use `spotify:…` URIs (Setup normalizes `https://open.spotify.com/...` on save).

```json
{
  "calm": "spotify:playlist:YOUR_CALM_ID",
  "focus": ["spotify:playlist:AAA", "spotify:playlist:BBB"],
  "hype": "spotify:playlist:YOUR_HYPE_ID"
}
```

- **`.env`:** comma-separated URIs per mood.

```env
SPOTIFY_PLAYLIST_CALM=spotify:playlist:YOUR_CALM_ID
SPOTIFY_PLAYLIST_FOCUS=spotify:playlist:YOUR_FOCUS_ID
SPOTIFY_PLAYLIST_HYPE=spotify:playlist:YOUR_HYPE_ID
```

**Default playback** is **context** (`SPOTIFY_PLAYBACK_MODE=context` in Compose when unset). **`main.py --spotify-playlist`** / **`--spotify-pool`** override **`SPOTIFY_PLAYBACK_MODE`** for that run only.

---

### Track pool mode (labeled CSV → nearest track by EEG-derived targets)

Use a **CSV** of tracks with **`track_id`**, **`energy`**, **`valence`**, **`tempo`** (BPM)—e.g. [TidyTuesday `spotify_songs.csv`](https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/2020-01-21/spotify_songs.csv). The app maps EEG to **`target_energy`**, **`target_valence`**, and **`target_tempo`**, picks a **near neighbor** in that space, then **`PUT /me/player/play`** with that track URI.

Optional **`.env`** knobs for those targets: **`SPOTIFY_TARGET_TEMPO_MIN`**, **`SPOTIFY_TARGET_TEMPO_MAX`**. For pool **URI validation** in some regions, set **`SPOTIFY_MARKET`** (ISO country code).

1. Copy the CSV to **`config/track_pool.csv`** (header must include **`track_id`**, **`energy`**, **`valence`**, **`tempo`**), **or** set **`SPOTIFY_TRACK_POOL_CSV`** to an absolute path.
2. **Essentials:** set **`SPOTIFY_PLAYBACK_MODE=pool`** and have Spotify auth connected (Setup flow token file, or `SPOTIFY_REFRESH_TOKEN` in `.env`). Client ID/secret usually come from **`config/constants.json`** unless you override via **`.env`** / Compose (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`). **`SPOTIFY_DEVICE_ID`** helps if you hit “no active device” (see troubleshooting).

**Minimal example:**

```env
SPOTIFY_PLAYBACK_MODE=pool
```

**Optional pool tuning** (defaults exist in code; omit unless you want to change behavior):

```env
# SPOTIFY_TRACK_POOL_CSV=/app/config/track_pool.csv   # default: ./config/track_pool.csv
# SPOTIFY_POOL_MIN_INTERVAL_S=10                      # default 10; min 10s enforced in code
# SPOTIFY_POOL_TOP_K=8
# SPOTIFY_POOL_ON_MOOD_CHANGE_ONLY=0                  # 1 = only change track when voted mood changes
# SPOTIFY_POOL_NEAR_END_THRESHOLD=0.97                # switch near end of current track
# SPOTIFY_POOL_END_DEBOUNCE_S=3                       # debounce end-trigger
# SPOTIFY_POOL_URGENT_SWITCH=1                        # allow early switch on major mood change
# SPOTIFY_POOL_URGENT_HOLD_S=20                       # min hold before urgent early switch
# SPOTIFY_POOL_HISTORY=24
# SPOTIFY_POOL_TEMPO_MIN=60   SPOTIFY_POOL_TEMPO_MAX=200
# SPOTIFY_POOL_WEIGHT_ENERGY=1  SPOTIFY_POOL_WEIGHT_VALENCE=1  SPOTIFY_POOL_WEIGHT_TEMPO=0.85
# SPOTIFY_SMOOTH_TRANSITIONS=1                        # fade down/up around switches
# SPOTIFY_TRANSITION_SECONDS=6                        # total transition duration
# SPOTIFY_FADE_STEPS=10                               # volume ramp steps
```

**Pool switching behavior:** track changes are primarily triggered near track end (`progress_ms / duration_ms >= SPOTIFY_POOL_NEAR_END_THRESHOLD`), with debounce (`SPOTIFY_POOL_END_DEBOUNCE_S`) and a stale-state fallback timer. Optional urgent early switch is controlled by `SPOTIFY_POOL_URGENT_SWITCH` + `SPOTIFY_POOL_URGENT_HOLD_S`.
**Smooth handoff:** when `SPOTIFY_SMOOTH_TRANSITIONS=1`, transitions use a Spotify-native volume envelope (fade-down → switch → fade-up), not true dual-deck beatmatching.

**Command-line mode (overrides `SPOTIFY_PLAYBACK_MODE` for this run)**

| Command | Spotify behavior |
|---------|------------------|
| `python main.py --spotify-playlist` | Mood → playlist/album (`context`) |
| `python main.py --spotify-pool` | CSV track pool → nearest feature match (needs pool file) |
| `python main.py` | Uses **`SPOTIFY_PLAYBACK_MODE`** from `.env` / Compose (default **context**) |

**Mood pipeline**

- **Features:** `energy` blends alpha-suppression min–max (longer history via **`SPOTIFY_ENERGY_HISTORY_MAX`**) with **gamma** arousal (**`SPOTIFY_GAMMA_AROUSAL_WEIGHT`**) and a slow EMA (**`SPOTIFY_ENERGY_SLOW_ALPHA`**, **`SPOTIFY_ENERGY_FAST_WEIGHT`**).
- **Stabilization:** EMA on energy/focus (**`SPOTIFY_MOOD_EMA_ALPHA`**), then majority vote over the last **`SPOTIFY_MOOD_VOTE_WINDOWS`** proposed moods; set **`SPOTIFY_MOOD_VOTE_OFF=1`** to disable voting.
- **Buckets:** `calm`, `deep_focus`, `focus`, `hype` (see `propose_mood` in `spotify_controller.py`). **`deep_focus`** uses the **focus** playlist URIs unless you add a `deep_focus` key to `config/spotify_mood_mapping.json`.

**4. Simulated EEG + Spotify (`main.py`)**

With **`SIMULATE=1`** in `.env`, **`docker compose up`** runs **`main.py`** with **simulated EEG** (see the Docker section above). The simulator **rotates** band-limited waveforms: **calm → focus → hype**, **`SIM_PHASE_SECONDS`** each (from `constants.json`, default 30), so moods and playlists should follow over time. **`SPOTIFY_MIN_SWITCH_S`** sets a **minimum delay** between Spotify **playlist/context** switches when mood changes (default **10** seconds; **`0`** = switch as soon as the voted mood changes).

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
