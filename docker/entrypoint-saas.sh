#!/bin/sh
# WebRedesign SaaS — Docker entrypoint
set -e

# Initialize database
python3 /app/app/saas_schema.py

echo "--- WebRedesign SaaS ---"
echo "Frontend: /app/frontend"
echo "Runner: $RUNNER_BASE_URL"
echo "DB: /data/saas.db"
echo "------------------------"

# Start the SaaS API server
exec python3 /app/app/saas_server.py
