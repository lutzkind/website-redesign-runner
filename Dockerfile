FROM nikolaik/python-nodejs:python3.11-nodejs22

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt
RUN npm install -g opencode-ai@latest impeccable@latest

COPY app /app/app
COPY skills /app/skills
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

ENV WEBSITE_REDESIGN_HOST=0.0.0.0 \
    WEBSITE_REDESIGN_PORT=4321 \
    WEBSITE_REDESIGN_ROOT=/data \
    WEBSITE_REDESIGN_SKILLS_DIR=/app/skills \
    WEBSITE_REDESIGN_DEFAULT_INDUSTRY=general \
    WEBSITE_REDESIGN_DEFAULT_SKILLS=website-audit,design-direction,layout-composer,frontend-art-direction,design-critic

EXPOSE 4321

ENTRYPOINT ["/app/entrypoint.sh"]
