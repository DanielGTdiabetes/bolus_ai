#!/usr/bin/env bash
set -euo pipefail

# Check that HomePage clears stale forecasts and surfaces a warning banner.
grep -n "forecastError" frontend/src/pages/HomePage.jsx
