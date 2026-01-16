# ========== STAGE 1: Build Frontend (React/Vite) ==========
FROM node:18-alpine as builder

WORKDIR /app/frontend

# Copy package files
COPY frontend/package*.json ./
RUN npm install

# Copy source code
COPY frontend/ .

# Build args for Vite (Baked into static files)
# For NAS, we want the frontend to call the backend on the same relative domain "/api"
# so we don't need absolute URLs.
ENV VITE_API_BASE_URL="" 
ENV VITE_RESTAURANT_MODE_ENABLED="false"
ARG BUILD_DATE="2026-01-16-FIX-V4-FORCE"
ARG FORCE_REBUILD=""
ENV BUILD_DATE="${BUILD_DATE}"
RUN echo "Frontend build cache buster: ${BUILD_DATE} ${FORCE_REBUILD}"

RUN npm run build

# ========== STAGE 2: Build Backend (Python) ==========
FROM python:3.11-slim

WORKDIR /app

# Install System Deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Frontend Build Result to Backend Static Folder
# This connects the two worlds!
COPY --from=builder /app/frontend/dist /app/app/static

# Setup Backend
ENV DATA_DIR=/app/data
ENV PYTHONPATH=/app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy Backend Code
COPY backend/ .

# Ensure data directories exist
RUN mkdir -p /app/data

# Startup Script
RUN echo '#!/bin/bash\n\
    uvicorn app.main:app --host 0.0.0.0 --port 8000' > /app/start.sh && chmod +x /app/start.sh

CMD ["./start.sh"]
