FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim@sha256:4f5d923c9dcea037f57bda425dd209f3ec643da2f0b74227f68d09dab0b3bb36
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv PYTHONUNBUFFERED=1 PYTHONUTF8=1
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY tests/fixtures ./tests/fixtures
RUN uv sync --locked --no-dev
CMD ["uv", "run", "--locked", "--no-dev", "datapilot-web", "serve"]
