# LARS Server
# Multi-stage build for Python + Node.js (Rabbitize browser automation)

# =============================================================================
# Stage 1: Build frontend
# =============================================================================
FROM node:18-slim AS frontend-builder

WORKDIR /app/frontend
COPY studio/frontend/package*.json ./
RUN npm ci --production=false
COPY studio/frontend/ ./
RUN npm run build

# =============================================================================
# Stage 2: Runtime
# =============================================================================
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Node.js for Rabbitize
    curl \
    gnupg \
    # Browser dependencies (Playwright/Chromium)
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    xdg-utils \
    libwoff1 \
    libharfbuzz-icu0 \
    libvpx7 \
    # FFmpeg for video/audio processing
    ffmpeg \
    # Git for version detection
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set up workspace
WORKDIR /app
ENV LARS_ROOT=/data
ENV PYTHONUNBUFFERED=1

# Install Python dependencies (lars package)
COPY lars/pyproject.toml lars/README.md ./lars/
COPY lars/lars ./lars/lars
RUN pip install --no-cache-dir ./lars

# Install studio backend dependencies
COPY studio/backend/requirements.txt ./studio/backend/
RUN pip install --no-cache-dir flask flask-cors duckdb gunicorn gevent

# Copy studio backend
COPY studio/backend ./studio/backend

# Copy built frontend
COPY --from=frontend-builder /app/frontend/build ./studio/frontend/build

# Install Rabbitize and Playwright
COPY rabbitize/package*.json ./rabbitize/
WORKDIR /app/rabbitize
RUN npm ci --production
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN npx playwright install chromium
RUN npx playwright install-deps chromium
COPY rabbitize/ ./

# Back to app root
WORKDIR /app

# Copy example cascades and tackle
COPY examples ./examples
COPY tackle ./tackle

# Create data directories
RUN mkdir -p /data/logs /data/graphs /data/states /data/images /data/audio /data/session_dbs

# Default environment (override with docker-compose or -e flags)
ENV LARS_USE_CLICKHOUSE_SERVER=true
ENV LARS_CLICKHOUSE_HOST=clickhouse
ENV LARS_CLICKHOUSE_PORT=9000
ENV FLASK_ENV=production

# Health check (uses cascade-definitions endpoint as proxy for health)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:5050/api/cascade-definitions || exit 1

EXPOSE 5050

# Run with gunicorn for production
CMD ["gunicorn", "--worker-class", "gevent", "--workers", "2", "--bind", "0.0.0.0:5050", "--chdir", "/app/studio/backend", "app:app"]
