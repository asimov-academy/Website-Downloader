FROM python:3.11-slim-bookworm

# Image oficial do app web single-page.

COPY --from=ghcr.io/astral-sh/uv:0.9.21 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright \
    PORT=8080

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen
RUN uv run playwright install --with-deps chromium

RUN mkdir -p downloads && chmod +x /app/entrypoint.sh

EXPOSE 8080

CMD ["/bin/bash", "/app/entrypoint.sh"]
