# Footballytics: one image for the API (web app + REST + WebSocket + MCP) and the archiver worker.

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/pyproject.toml ./backend/
COPY backend/footballytics ./backend/footballytics
RUN pip install "./backend[cloud]"
COPY --from=web /web/dist ./web
ENV WEB_DIST=/app/web \
    MATCHDAY=9 \
    SPEED=4 \
    AUTOLOOP=1
RUN useradd --system --uid 10001 app && chown -R app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "footballytics.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
