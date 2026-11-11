# e2e

요구사항 2절 '기본 사용 시나리오'를 실제 브라우저에서 재생하는 E2E 테스트(#397). 배포 단위는 아니지만 backend·web·extension을 함께 띄워 확인하므로 최상위에 둔다.

## 명령

저장소 루트에서 실행한다. Docker(Compose)와, 루트 `.env`의 `OPENAI_API_KEY`가 필요하다.

- 실행: `e2e/run.sh` (Playwright 인자를 그대로 넘긴다. 예: `e2e/run.sh --grep "첫 분석"`)
- 같은 체크아웃에서는 한 번에 하나만 돌린다(`e2e/node_modules`·`test-results`를 함께 쓴다). 동시에 돌리려면 worktree를 따로 둔다. 스택(DB·작업자)은 실행마다 따로다.
- 결과: 실패하면 `e2e/test-results/`(trace·스크린샷, `server.log`에 백엔드·작업자 로그)와 `e2e/playwright-report/`. trace는 `npx playwright show-trace <파일>`로 연다.
- 타입 검사: `cd e2e && npm run typecheck`

## 구성

- `run.sh`가 compose 프로젝트를 실행마다 따로 만든다(`compose.yaml` 위에 `e2e/compose.yaml`을 겹친다). 호스트 포트를 열지 않아 개발 스택과 함께 돌아도 된다. 끝나면 볼륨·이미지까지 지운다.
- 순서: 이미지 빌드 → `migrate` + `fixtures/seed.json` 적재 → 백엔드·작업자·웹 → Playwright 컨테이너(`support/in-container.sh`).
- Playwright 컨테이너는 확장을 복사본에서 빌드하고(저장소의 `node_modules`·개발 빌드를 덮어쓰지 않는다), `localhost:8000`·`localhost:5173`을 compose 서비스로 잇는다(`support/forward.mjs`). 그래서 확장·웹은 개발 기본 주소 그대로다.
- 로그인은 dev-login(DEBUG + `DEV_LOGIN_ENABLED`)으로 웹 세션을 만들고, 확장 연결은 웹 '로그인·확장 연결' 화면에서 실제로 누른다.
- 분석 시작: Playwright는 크롬 우클릭 메뉴를 누를 수 없어, 백그라운드에서 메뉴 클릭 이벤트(`contextMenus.onClicked.dispatch`)를 보낸다. 앱 코드는 메뉴를 누를 때와 같다. 테스트 페이지는 Playwright가 API 출처(`localhost:8000/e2e/...`) 주소로 내주어, `host_permissions`로 문장 추출 스크립트가 주입된다.
- 사이드 패널은 사용자 동작 안에서만 열리므로 `sidepanel.html`을 같은 창의 탭으로 연다.

## 규칙

- 실제 OpenAI를 부른다(가짜 서버를 만들지 않는다). 리뷰·검증 중에 사람이 시키지 않았으면 돌리지 않는다. CI는 `OPENAI_API_KEY_E2E` 시크릿이 있을 때만 돈다.
- 학습자가 보는 것(문구·배지·역할)과 운영자가 확인할 수 있는 바깥 결과만 확인한다. CSS 클래스·컴포넌트 구조에 기대지 않고, 요소는 역할·이름·문구로 찾는다(DESIGN.md 문구 기준).
- 모델 답은 매번 달라 번역문·용법 이름을 비교하지 않는다. '번역이 있다', '확인 중이 사라졌다'처럼 흔들리지 않는 사실만 본다.
- 시나리오마다 새 브라우저와 새 계정으로 시작한다.
- 고정 문장은 관리자가 새로 쓴 문장만 쓰고(`fixtures/sentences.ts`), 필요한 문법·단어 행은 `fixtures/seed.json`에 둔다(`fixtures/README.md`).
