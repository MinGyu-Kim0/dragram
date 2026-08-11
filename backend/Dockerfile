FROM ghcr.io/astral-sh/uv:0.11.32 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

COPY . .

EXPOSE 8000
CMD ["uv", "run", "--frozen", "python", "manage.py", "runserver", "0.0.0.0:8000"]
