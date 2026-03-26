# NEURO-RAVE

**Real-time EEG-driven music generation system**

NEURO-RAVE streams EEG data from BioSemi hardware, processes neural
features in real time, and uses those features to influence live music
generation.

------------------------------------------------------------------------

# System Overview

BioSemi → ActiView (TCP) → Python TCP Client → LSL Stream → Processing +
Feature Extraction → Dashboard + Music Generation

------------------------------------------------------------------------

# Project Structure

NEURO-RAVE/ ├── dashboard/ \# Real-time visualization ├── hardware/ \#
BioSemi / acquisition logic ├── music-gen/ \# Music generation API logic
├── processing/ \# Signal processing + feature extraction ├── streaming/
\# TCP → LSL bridge ├── Dockerfile ├── requirements.txt └── README.md

Each directory represents a functional module.

------------------------------------------------------------------------
# Environment Setup

## Docker

```bash
docker compose build
docker compose up
```

To stop: `docker compose down`

### Running other scripts in the container

```bash
# Open a shell inside the running container
docker compose exec neuro-rave bash

# Run a one-off script
docker compose run --rm neuro-rave python src/streaming/tcp_test.py
```

Source files are volume-mounted, so local edits are reflected immediately without rebuilding.

### Spotify Demo: Test Music Generation

**Requirements:** Spotify Premium account + active playback device

#### Quick Start (Local Development - Recommended)

1. **Get your refresh token:**
```bash
python3 get_spotify_refresh_token.py
```
Browser opens automatically → log in with Premium account → approve → done!

2. **Activate your Spotify device:**
   - Open Spotify app on your computer/phone
   - Start playing any song (this enables API control)

3. **Run the demo:**
```bash
# Test different moods (5 minutes each)
SPOTIFY_FIXED_MOOD=hype SPOTIFY_FIXED_DURATION_S=300 python3 scripts/spotify_fixed_mood_demo.py
SPOTIFY_FIXED_MOOD=calm SPOTIFY_FIXED_DURATION_S=300 python3 scripts/spotify_fixed_mood_demo.py
SPOTIFY_FIXED_MOOD=focus SPOTIFY_FIXED_DURATION_S=300 python3 scripts/spotify_fixed_mood_demo.py
```

**What happens:** Script connects to Spotify → starts the mood playlist → shows progress → stops after duration.

#### Docker (Playback)

Use Docker for playback, but **get the refresh token locally** (recommended).

Why: the refresh-token script runs a local callback server at `http://127.0.0.1:8080/callback`.
Spotify may warn that `http://localhost:...` is “not secure” in the dashboard; `127.0.0.1`
is the reliable option. Running the callback server inside Docker can also cause
`ERR_CONNECTION_REFUSED` in the browser unless you set up port publishing + binding.

```bash
# 1) Get refresh token locally (host machine)
python get_spotify_refresh_token.py

# 2) Run demo in Docker (make sure Spotify is active on host)
SPOTIFY_FIXED_MOOD=hype SPOTIFY_FIXED_DURATION_S=300 \
  docker compose run --rm neuro-rave python scripts/spotify_fixed_mood_demo.py
```

**Note:** Spotify app must be running on your host machine for Docker to control playback.

## Conda (local development)

```bash
conda create -n neuro-rave python=3.11 -y
conda activate neuro-rave
pip install -r requirements.txt
python main.py
```

#### Troubleshooting Spotify

**❌ "Premium required"**
- You need Spotify Premium for playback control
- Free accounts can only read playlists/metadata

**❌ "No active device found"**
- Open Spotify app and start playing any song first
- This "activates" your device for API control

**❌ "User not registered for this application"**
- Add your Spotify email to the app's user list in Spotify Developer Dashboard
- For >25 users, apply for "Extension Mode"

------------------------------------------------------------------------

# Dependency Rules

All Python dependencies are: - Explicitly version-pinned - Defined in
requirements.txt - Installed only through Docker builds

## Adding a Dependency

1.  Add package with exact version to requirements.txt
2.  Rebuild the container: docker compose build docker compose up

## Removing a Dependency

1.  Delete it from requirements.txt
2.  Rebuild without cache: docker compose build --no-cache docker
    compose up

------------------------------------------------------------------------

# Do NOT

-   Install packages manually inside containers
-   Leave versions unpinned
-   Mix local virtual environments with Docker
-   Upgrade NumPy / MNE without testing the full pipeline

Real-time EEG systems are sensitive to dependency instability.

------------------------------------------------------------------------

# Development Workflow

### Normal Code Changes

If using volume mounting: - Edit Python files locally - No rebuild
required

### Dependency Changes

-   Update requirements.txt
-   Rebuild container

------------------------------------------------------------------------

# ⚡ Reproducibility Policy

The Dockerfile locks: - OS environment - Python version - All dependency
versions

This ensures: - Identical environments across machines - Stable
real-time behavior - Reproducible research

------------------------------------------------------------------------

# FAQ

**`zsh: command not found: docker`**

Docker Desktop must be running. Open it from Applications, wait for the whale icon in the menu bar. If still not found, the symlink may be broken:
```bash
sudo ln -sf /Applications/Docker.app/Contents/Resources/bin/docker /usr/local/bin/docker
```

**`docker-credential-desktop: executable file not found`**

Remove `"credsStore": "desktop"` from `~/.docker/config.json`.

**`ModuleNotFoundError: No module named 'pylsl'`**

You're using the wrong Python. Activate the conda env first:
```bash
conda activate neuro-rave
python main.py
```

**`ConnectionRefused` when running in Docker**

The container can't reach `127.0.0.1` on your host. The `BIOSEMI_HOST` env var in `docker-compose.yml` is set to `host.docker.internal` to handle this. Make sure Docker Desktop is up to date.

**Docker build fails pulling the base image**

Check your internet connection and that Docker Desktop is running. If behind a proxy, configure it in Docker Desktop settings.

**Changes to code not showing in container**

Source files are volume-mounted. If you added a new top-level file (not under `src/`), add it to the `volumes` section in `docker-compose.yml`. Dependency changes always require `docker compose build`.

------------------------------------------------------------------------

# Core Principle

Reproducibility \> Convenience.

A stable neural streaming system is more important than quick local
installs.
