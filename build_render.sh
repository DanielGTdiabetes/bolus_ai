#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "Building Frontend..."
cd frontend
# Use npm ci for consistent dependency installation
npm ci
# Set Node memory limit to ~2.5GB to prevent OOM on Render build instances
export NODE_OPTIONS="--max-old-space-size=2560"
npm run build
cd ..

echo "Installing Backend Dependencies..."
pip install -r backend/requirements.txt

echo "Moving Frontend Build to Backend..."
# Ensure destination exists and remove stale hashed bundles from previous builds.
# Render may otherwise keep an old index/assets pair when the source tree already
# contains a prebuilt frontend.
mkdir -p backend/app/static
find backend/app/static -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
# Copy dist contents to static
cp -r frontend/dist/* backend/app/static/

echo "Build Complete!"
