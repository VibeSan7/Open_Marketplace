FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv
FROM python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser . .
USER appuser
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM runtime AS test
USER root
RUN uv sync --locked --dev --no-install-project \
    && mkdir -p /app/.import_linter_cache \
    && chown appuser:appuser /app/.import_linter_cache
USER appuser
CMD ["python", "manage.py", "test", "open_marketplace", "-v", "2"]
