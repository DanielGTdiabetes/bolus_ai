#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "Building Frontend..."
cd frontend
npm install
npm run build
cd ..

echo "Installing Backend Dependencies..."
pip install -r backend/requirements.txt

echo "Moving Frontend Build to Backend..."
# Ensure destination exists
mkdir -p backend/app/static
# Copy dist contents to static
cp -r frontend/dist/* backend/app/static/

echo "Build Complete!"
