# --- Stage 1: Build Frontend ---
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy package files first for caching
COPY frontend/package.json frontend/package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY frontend/ ./

# Build the frontend
# This generates the static files in /app/frontend/dist
ENV NODE_OPTIONS="--max-old-space-size=2048"
RUN npm run build

# --- Stage 2: Setup Backend & Undo ---
FROM python:3.11-slim

WORKDIR /app

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/backend/data \
    CONFIG_PATH=/app/config/config.json

# System dependencies (including pg_isready if needed, or just basics)
# libpq-dev is often needed for psycopg2 (or using psycopg2-binary)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Backend Dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy Backend Code
COPY backend/ /app/backend/
COPY backend/app /app/app

# --- MERGE: Copy built frontend from Stage 1 ---
# We put it where main.py expects it: app/static or backend/app/static
# main.py line 182: static_dir = Path(__file__).parent / "static" -> /app/app/static
RUN mkdir -p /app/app/static
COPY --from=frontend-builder /app/frontend/dist /app/app/static

# Create data directory
RUN mkdir -p ${DATA_DIR} && chmod 777 ${DATA_DIR}

# Copy Config (can be overridden by volume)
COPY config/ /app/config/

# Expose port
EXPOSE 8000

# Start command
# We use the start.sh if it exists, or call uvicorn directly.
# Let's use a simplified start command for the container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
