#!/usr/bin/env bash
set -euo pipefail

mkdir -p /data/jobs /data/previews

if [ -x /root/cli-persistence/bin/gws ] && [ ! -e /usr/local/bin/gws ]; then
  ln -s /root/cli-persistence/bin/gws /usr/local/bin/gws
fi

if [ -x /root/.local/bin/gws-email ] && [ ! -e /usr/local/bin/gws-email ]; then
  ln -s /root/.local/bin/gws-email /usr/local/bin/gws-email
fi

exec python3 /app/app/main.py
