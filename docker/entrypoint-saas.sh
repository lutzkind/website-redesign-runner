#!/bin/sh
# WebRedesign SaaS — Docker entrypoint
set -e

if [ -x /root/cli-persistence/bin/gws ] && [ ! -e /usr/local/bin/gws ]; then
  ln -s /root/cli-persistence/bin/gws /usr/local/bin/gws
fi

if [ -x /root/.local/bin/gws-email ] && [ ! -e /usr/local/bin/gws-email ]; then
  ln -s /root/.local/bin/gws-email /usr/local/bin/gws-email
fi

# Initialize database
python3 /app/app/saas_schema.py

echo "--- WebRedesign SaaS ---"
echo "Frontend: /app/frontend"
echo "Runner: $RUNNER_BASE_URL"
echo "DB: /data/saas.db"
echo "------------------------"

# Start the SaaS API server
exec python3 /app/app/saas_server.py
