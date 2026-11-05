#!/usr/bin/env sh
# 스토어 스크린샷·홍보 이미지를 Playwright 컨테이너에서 만든다(#398). extension/에서 npm run shots:store.
# 빌드 결과의 가이드 화면을 찍으므로 먼저 npm run zip:store(또는 npm run build)를 한다.
set -eu
cd "$(dirname "$0")/../.."
FONTS=/mnt/c/Windows/Fonts # Windows Chrome과 같은 글꼴(맑은 고딕·Yu Gothic)
test -d "$FONTS" || { echo "Windows 글꼴 폴더가 없다: $FONTS" >&2; exit 1; }
# 스토어 빌드가 있으면 그것을, 없으면 개발 빌드를 찍는다(가이드 화면은 둘이 같다).
SITE=.output/store/chrome-mv3
test -f $SITE/guide.html || SITE=.output/chrome-mv3
test -f $SITE/guide.html || { echo "먼저 npm run zip:store 또는 npm run build" >&2; exit 1; }
VERSION=$(node -p "require('./package.json').version")
# 브라우저 이미지는 playwright-core와 같은 버전이어야 한다.
PW=$(node -p "require('playwright-core/package.json').version")
# 서버도 컨테이너 안에서 띄운다. Docker Desktop(WSL)은 호스트 localhost에 닿지 않는다.
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/ext" -v "$FONTS:/usr/share/fonts/win:ro" -w /ext \
  "mcr.microsoft.com/playwright:v$PW-jammy" \
  node scripts/store-shots/shots.mjs "$SITE" ".output/store/screenshots-$VERSION"
