#!/usr/bin/env bash
# 개발 PC에서 운영 서버로 backend 이미지와 운영 설정을 보낸다. 저장소 루트에서 실행한다.
#   DEPLOY_HOST=ubuntu@dragram.app infra/deploy.sh
# 서버에는 Docker와 ~/dragram/.env가 미리 있어야 한다(infra/README.md).
set -euo pipefail

host=${DEPLOY_HOST:?ssh 대상을 DEPLOY_HOST로 준다(예: ubuntu@dragram.app)}

# 이미지 태그(커밋)로 되돌릴 수 있게, 커밋하지 않은 변경(추적하지 않는 새 파일 포함)은 올리지 않는다.
if [ -n "$(git status --porcelain -- backend infra)" ]; then
  echo "backend/ 또는 infra/에 커밋하지 않은 변경이 있다." >&2
  exit 1
fi
image="dragram-backend:$(git rev-parse --short HEAD)"

# 무시된 파일(.env 등)도 들어가지 않게 커밋된 트리만 빌드 입력으로 쓴다.
git archive HEAD:backend | docker build --target prod -t "$image" -
docker save "$image" | gzip | ssh "$host" 'gunzip | docker load'
ssh "$host" 'mkdir -p ~/dragram/caddy'
scp infra/compose.yaml "$host:dragram/"
scp infra/Caddyfile "$host:dragram/caddy/"
ssh "$host" "cd ~/dragram \
  && docker tag $image dragram-backend:current \
  && docker compose run --rm backend python manage.py migrate \
  && docker compose up -d --remove-orphans \
  && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile"
echo "배포함: $image"
