FROM ghcr.io/astral-sh/uv:0.12.13 AS uv

FROM python:3.14-slim AS base
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

# 개발용: 테스트 의존성까지 설치한다. 코드는 compose가 마운트한다.
FROM base AS dev
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# 배포용(기본 대상): 테스트 의존성과 테스트 코드를 넣지 않는다.
FROM base AS prod
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
COPY . .
RUN useradd --system app
USER app
EXPOSE 8000
# 분석 응답은 LLM 스트림이 끝날 때까지 작업자를 잡는다(analysis/llm.py STREAM_DEADLINE_SECONDS).
# 기본 30초 타임아웃이면 그 전에 작업자가 죽으므로, 상한(60초)에 마지막 조각 대기(30초)를
# 더한 것보다 길게 둔다.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--timeout", "120"]
