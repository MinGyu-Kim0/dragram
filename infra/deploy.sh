#!/usr/bin/env bash
# 개발 PC에서 운영 서버로 backend 이미지, 웹 빌드 결과, 운영 설정을 보낸다. 저장소 루트에서 실행한다.
#   DEPLOY_HOST=ubuntu@dragram.app infra/deploy.sh
# 서버에는 Docker와 ~/dragram/.env가 미리 있어야 한다(infra/README.md).
set -euo pipefail

host=${DEPLOY_HOST:?ssh 대상을 DEPLOY_HOST로 준다(예: ubuntu@dragram.app)}

# 이미지 태그(커밋)로 되돌릴 수 있게, 커밋하지 않은 변경(추적하지 않는 새 파일 포함)은 올리지 않는다.
if [ -n "$(git status --porcelain -- backend infra web .env.production)" ]; then
  echo "backend/, infra/, web/ 또는 .env.production에 커밋하지 않은 변경이 있다." >&2
  exit 1
fi
image="dragram-backend:$(git rev-parse --short HEAD)"

# 웹은 커밋된 web/과 운영 공개 값(.env.production)만으로 빌드한다. 개발용 .env는 섞지 않는다.
src=$(mktemp -d)
trap 'rm -rf "$src"' EXIT
git archive HEAD web .env.production | tar -x -C "$src"
if ! grep -q '^VITE_GOOGLE_CLIENT_ID=.' "$src/.env.production"; then
  echo ".env.production의 VITE_GOOGLE_CLIENT_ID가 비어 있다. 운영 웹에서 로그인할 수 없다." >&2
  exit 1
fi
# CI·web/Dockerfile과 같은 Node 22로 빌드한다.
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$src:/src" -w /src/web node:22-alpine \
  sh -c 'npm ci --no-audit --no-fund && npm run build'

# 무시된 파일(.env 등)도 들어가지 않게 커밋된 트리만 빌드 입력으로 쓴다.
git archive HEAD:backend | docker build --target prod -t "$image" -
docker save "$image" | gzip | ssh "$host" 'gunzip | docker load'
ssh "$host" 'mkdir -p ~/dragram/caddy ~/dragram/www && rm -rf ~/dragram/www/web.new && mkdir ~/dragram/www/web.new'
tar -C "$src/web/dist" -cz . | ssh "$host" 'tar -xz -C ~/dragram/www/web.new'
scp infra/compose.yaml "$host:dragram/"
scp infra/Caddyfile "$host:dragram/caddy/"
ssh "$host" bash -s -- "$image" <<'REMOTE'
set -euo pipefail
image=$1
cd ~/dragram
docker tag "$image" dragram-backend:current
docker compose run --rm backend python manage.py migrate
docker compose up -d --remove-orphans
# admin 정적 파일은 이미지가 빌드할 때 모아 둔 것을 꺼낸다.
rm -rf www/static.new && mkdir www/static.new
docker run --rm --entrypoint tar "$image" -C /app/staticfiles -c . | tar -x -C www/static.new
# backend가 새로 뜬 뒤 폴더째 바꾼다. Caddy가 반쯤 바뀐 파일을 내주지 않는다.
for d in web static; do
  rm -rf "www/$d.old"
  if [ -d "www/$d" ]; then mv "www/$d" "www/$d.old"; fi
  mv "www/$d.new" "www/$d"
  rm -rf "www/$d.old"
done
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
REMOTE
echo "배포함: $image"
