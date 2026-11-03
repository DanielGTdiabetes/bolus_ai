FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV NODE_OPTIONS="--max-old-space-size=2048"
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

ENV DATA_DIR=/tmp/data

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Render uses this Dockerfile; serve the same current portal as the NAS.
RUN rm -rf /app/app/static
COPY --from=frontend-builder /app/frontend/dist /app/app/static

RUN mkdir -p "${DATA_DIR}"

RUN chmod +x start.sh
CMD ["./start.sh"]
