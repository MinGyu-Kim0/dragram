#!/usr/bin/env bash
# 개발 PC에서 운영 서버로 backend 이미지와 운영 설정을 보낸다. 저장소 루트에서 실행한다.
#   DEPLOY_HOST=ubuntu@dragram.app infra/deploy.sh
# 서버에는 Docker와 ~/dragram/.env가 미리 있어야 한다(infra/README.md).
set -euo pipefail

host=${DEPLOY_HOST:?ssh 대상을 DEPLOY_HOST로 준다(예: ubuntu@dragram.app)}

# 이미지 태그(커밋)로 되돌릴 수 있게, 커밋하지 않은 변경은 올리지 않는다.
if ! git diff --quiet HEAD -- backend infra; then
  echo "backend/ 또는 infra/에 커밋하지 않은 변경이 있다." >&2
  exit 1
fi
image="dragram-backend:$(git rev-parse --short HEAD)"

docker build --target prod -t "$image" backend
docker save "$image" | gzip | ssh "$host" 'gunzip | docker load'
ssh "$host" 'mkdir -p ~/dragram'
scp infra/compose.yaml infra/Caddyfile "$host:dragram/"
ssh "$host" "cd ~/dragram \
  && docker tag $image dragram-backend:current \
  && docker compose run --rm backend python manage.py migrate \
  && docker compose up -d --remove-orphans"
echo "배포함: $image"
