#!/usr/bin/env sh
# e2e 컨테이너 안에서 확장을 빌드하고 Playwright를 돌린다. 인자는 playwright test에 넘긴다.
set -eu
# 저장소의 extension/node_modules와 개발 빌드(.output)를 덮어쓰지 않게 복사본에서 빌드한다.
EXT=/tmp/extension
mkdir -p "$EXT"
tar -C /repo/extension --exclude=node_modules --exclude=.output --exclude=.wxt -cf - . | tar -C "$EXT" -xf -
(cd "$EXT" && npm ci --no-audit --no-fund --loglevel=error && WXT_E2E=true npx wxt build >/dev/null)
npm ci --no-audit --no-fund --loglevel=error
EXTENSION_PATH="$EXT/.output/chrome-mv3" exec npx playwright test "$@"
