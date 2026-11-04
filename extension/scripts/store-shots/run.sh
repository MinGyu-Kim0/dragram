#!/usr/bin/env sh
# 스토어 스크린샷·홍보 이미지를 Playwright 컨테이너에서 만든다(#398). extension/에서 npm run shots:store.
# 빌드 결과(.output/chrome-mv3)의 가이드 화면을 찍으므로 먼저 npm run build를 한다.
# 이미지 태그는 package.json의 playwright-core 버전과 같아야 한다.
set -eu
cd "$(dirname "$0")/../.."
FONTS=/mnt/c/Windows/Fonts # Windows Chrome과 같은 글꼴(맑은 고딕·Yu Gothic)
test -d "$FONTS" || { echo "Windows 글꼴 폴더가 없다: $FONTS" >&2; exit 1; }
test -f .output/chrome-mv3/guide.html || { echo "먼저 npm run build" >&2; exit 1; }
VERSION=$(node -p "require('./package.json').version")
# 서버도 컨테이너 안에서 띄운다. Docker Desktop(WSL)은 호스트 localhost에 닿지 않는다.
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/ext" -v "$FONTS:/usr/share/fonts/win:ro" -w /ext \
  mcr.microsoft.com/playwright:v1.46.1-jammy \
  node scripts/store-shots/shots.mjs .output/chrome-mv3 ".output/store/screenshots-$VERSION"
