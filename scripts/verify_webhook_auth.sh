#!/usr/bin/env bash
set -euo pipefail

# Ensure the webhook auth gate references ALLOW_UNAUTH_NUTRITION_INGEST
grep -n "ALLOW_UNAUTH_NUTRITION_INGEST" backend/app/api/integrations.py
