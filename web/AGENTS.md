# web

React + Vite + TypeScript 웹페이지(내 일본어, 학습 카드, 작문 평가). 패키지는 npm으로 관리한다.

## 명령

`web/`에서 실행한다.

- 개발 서버: 루트에서 `docker compose up -d` → `http://localhost:5173`. compose 없이 `npm run dev`도 된다.
- 테스트: `npm test` (Vitest + Testing Library, jsdom)
- 린트: `npm run lint` (oxlint)
- 포맷: `npm run format`, 확인만 할 때 `npm run format:check` (Prettier)
- 타입 검사: `npm run typecheck`
- 빌드: `npm run build` → `dist/`

## 규칙

- 의존성을 바꾸면 `package-lock.json`도 함께 커밋한다. compose를 쓰면 `docker compose build web` 후 `docker compose up -d -V web`으로 node_modules를 다시 만든다.
- 테스트는 대상 파일 옆에 `*.test.ts(x)`로 둔다.
- 화면 색·문구는 루트 `DESIGN.md`를 따른다.
- 운영 구성·배포 절차는 [`infra/README.md`](../infra/README.md)를 따른다. `Dockerfile`은 로컬 개발 서버용이다.
