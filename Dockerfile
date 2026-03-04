# ---- Base Image ----
FROM python:3.11-slim

# ---- Environment Variables ----
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ---- System Dependencies ----
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    cmake \
    git \
    && git clone --depth 1 --branch v1.16.2 https://github.com/sccn/liblsl.git /tmp/liblsl \
    && cd /tmp/liblsl \
    && cmake -B build -DCMAKE_INSTALL_PREFIX=/usr/local \
    && cmake --build build --config Release -j$(nproc) \
    && cmake --install build \
    && ldconfig \
    && rm -rf /tmp/liblsl \
    && rm -rf /var/lib/apt/lists/*

# ---- Set Work Directory ----
WORKDIR /app

# ---- Install Python Dependencies ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Copy Source Code ----
COPY src/ ./src/
COPY main.py .

# ---- Default Command ----
CMD ["python", "main.py"]