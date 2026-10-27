# extension

크롬 확장(MV3). WXT + React + TypeScript로 만들고, 결과는 사이드 패널에 보여준다. 패키지는 npm으로 관리한다.

## 명령

`extension/`에서 실행한다.

- 빌드: `npm run build` → `.output/chrome-mv3/`. 크롬 `chrome://extensions`에서 개발자 모드를 켜고 "압축해제된 확장 프로그램 로드"로 이 폴더를 불러온다.
- 개발 모드: `npm run dev` (파일을 고치면 다시 빌드한다. WSL에서는 브라우저를 자동으로 띄우지 못하므로 위처럼 `.output/chrome-mv3-dev/`를 불러온다. Windows 크롬에서는 `\\wsl.localhost\<배포판>\...\extension\.output\chrome-mv3-dev` 경로로 고른다)
- 백엔드 주소: 기본은 `http://localhost:8000`(compose 백엔드). 다른 주소로 빌드하려면 셸 환경변수로 준다(`WXT_API_BASE_URL=https://... npm run build`). manifest의 `host_permissions`도 이 값으로 정해진다.
- 스토어용 zip: `npm run zip:store` → `.output/store/dragram-extension-<버전>-chrome.zip`. API·웹 주소를 `https://dragram.app`으로 두고 개발용 `key`를 뺀다(확장 ID는 스토어가 정한다). 스토어가 정한 ID는 서버 `~/dragram/.env`의 `VITE_EXTENSION_ID`에 넣고 다시 배포해야 운영 웹이 확장에 연결할 수 있다. 올릴 때마다 `package.json`의 `version`을 올린다.
- 테스트: `npm test` (Vitest + Testing Library, jsdom. `browser.*` API는 WXT의 fake-browser로 대체된다)
- 린트: `npm run lint` (oxlint)
- 포맷: `npm run format`, 확인만 할 때 `npm run format:check` (Prettier)
- 타입 검사: `npm run typecheck`

## 규칙

- 진입점은 `entrypoints/`에 두고, manifest는 `wxt.config.ts`와 진입점에서 만든다. `manifest.json`을 직접 쓰지 않는다.
- 권한(`permissions`, `host_permissions`)은 실제로 쓰는 것만 추가한다.
- 아이콘(`public/icon/*.png`)은 `web/public/favicon.svg`에서 만든 PNG다. 로고를 바꾸면 SVG를 고친 뒤 같은 크기(16·32·48·96·128)로 다시 만든다.
- 테스트는 대상 파일 옆에 `*.test.ts(x)`로 둔다.
- 화면 색·문구는 루트 `DESIGN.md`를 따른다.
