FROM python:3.11-slim

WORKDIR /app

# Minimal runtime dependencies plus screenshot capture support
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    chromium \
    fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/* \
  && pip install --no-cache-dir requests

COPY app/saas_schema.py /app/app/saas_schema.py
COPY app/saas_server.py /app/app/saas_server.py
COPY app/capture_screenshot.mjs /app/app/capture_screenshot.mjs
COPY docker/entrypoint-saas.sh /app/entrypoint-saas.sh
COPY frontend /app/frontend

RUN chmod +x /app/entrypoint-saas.sh

EXPOSE 4322

ENV SAAS_PORT=4322 \
    SAAS_HOST=0.0.0.0 \
    RUNNER_BASE_URL=http://runner:4321

ENTRYPOINT ["/app/entrypoint-saas.sh"]
