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

# Environment Setup (Docker Required)

This project is fully containerized.

## Build the Image

docker compose build

or

docker build -t neuro-rave .

## Run the Application

docker compose up

or

docker run -p 8050:8050 neuro-rave

## Stop the Application

docker compose down

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

# Core Principle

Reproducibility \> Convenience.

A stable neural streaming system is more important than quick local
installs.
