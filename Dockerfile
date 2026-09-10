# ==============================================================================
# DeskPilot — Multi-Agent Autonomous Workspace
# AWS "Agents for Humans" Hackathon Production Dockerfile
# ==============================================================================

FROM python:3.12-slim

# Working directory
WORKDIR /app

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DESKPILOT_WEB_MODE=1 \
    DESKPILOT_DOCKER=1 \
    HOST=0.0.0.0 \
    PORT=5000 \
    DEFAULT_OUTPUT_DIR=/app/output

# System dependencies for document generation, fonts, and healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    fontconfig \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies
COPY requirements.txt .
# Filter Windows-specific .NET bindings for headless Linux container
RUN sed -i '/pywebview/d;/clr_loader/d;/pythonnet/d' requirements.txt && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY agents/ ./agents/
COPY assets/ ./assets/
COPY sample_data/ ./sample_data/
COPY main.py .

# Create persistent runtime directories
RUN mkdir -p /app/output /app/chats /app/logs

# Expose Web Interface & API Port
EXPOSE 5000

# Container Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/status || exit 1

# Run DeskPilot in Docker Web Server mode
CMD ["python", "main.py", "--docker"]
