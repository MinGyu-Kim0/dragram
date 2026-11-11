#!/usr/bin/env bash
# E2E를 compose 스택에서 돌린다(#397). 실제 OpenAI를 부르므로 저장소 루트 .env에 OPENAI_API_KEY가 있어야 한다.
# 사용: e2e/run.sh [playwright test 인자...]   예: e2e/run.sh --grep "첫 분석"
set -euo pipefail
cd "$(dirname "$0")/.."
# 실행마다 프로젝트를 따로 두어 개발 스택(dragram)·동시에 도는 다른 실행과 DB·작업자를 섞지 않는다.
export COMPOSE_PROJECT_NAME="${E2E_PROJECT:-dragram-e2e-$$}"
export COMPOSE_FILE=compose.yaml:e2e/compose.yaml
# 컨테이너가 저장소에 쓰는 파일(결과·로그)이 내 소유가 되게 한다.
export UID GID="$(id -g)"

cleanup() {
  mkdir -p e2e/test-results
  docker compose logs --no-color backend worker >e2e/test-results/server.log 2>&1 || true
  docker compose down -v --rmi local --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose build backend web
# 시나리오에 필요한 단어·문법만 미리 넣는다(fixtures/README.md).
docker compose run --rm backend sh -c \
  "python manage.py migrate && python manage.py loaddata /e2e-fixtures/seed.json"
docker compose up -d backend worker web
docker compose run --rm e2e "$@"
