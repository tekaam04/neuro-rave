# ---- Base Image ----
FROM python:3.11-slim

# ---- Environment Variables ----
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ---- System Dependencies ----
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# ---- Set Work Directory ----
WORKDIR /app

# ---- Install Python Dependencies ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# # ---- Copy Source Code ----
# COPY src/ ./src/

# # ---- Default Command ----
# CMD ["python", "src/eeg_realtime/dashboard/app.py"]