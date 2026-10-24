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
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# 배포용(기본 대상): 테스트 의존성과 테스트 코드를 넣지 않는다.
FROM base AS prod
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
COPY . .
RUN useradd --system app
USER app
EXPOSE 8000
# 분석 LLM 작업은 작업자(`python manage.py analysis_worker`)가 하고, 서버는 그 결과를 기다리는
# 연결을 비동기로 붙잡는다(ADR 0005). 작업 시간 제한은 작업자 쪽(analysis/queue.py)에 있다.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
