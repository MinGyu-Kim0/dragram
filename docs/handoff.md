# 인계 메모 (2026-10-18)

설계(요구사항·DB 스키마·디자인 기준)는 마감됐다. 다음은 구현 시작이다. 사용자와는 한국어로 대화한다.

## 문서 위치
- 용어: `GLOSSARY.md` — 코드·커밋·이슈에 이 용어를 그대로 쓴다
- 요구사항(최종 기준): `docs/requirements.md`
- DB 스키마(설계 시점 기준): `docs/schema/schema.md`, 원본 `docs/schema/erd.json`(ERDCloud)
- 디자인 기준: `DESIGN.md`
- 설계 결정 기록(왜 그렇게 정했나, 시간순·뒤 절 우선): `docs/design-decisions.md`
- ADR: `docs/adr/`

## 규칙 문서
- `AGENTS.md`: 에이전트 공통 규칙(불변식, 작업 방식, git)
- `CODING_STANDARDS.md`: 코드 작성·리뷰 기준
- `.github/CONTRIBUTING.md`: 브랜치·커밋·PR·이슈 작성법, 병합 방식
- `CLAUDE.md`: `@AGENTS.md` 한 줄. 실제 규칙은 `AGENTS.md`에 쓴다.
- `docs/agents/`: `/setup-matt-pocock-skills` 결과(이슈 트래커, 트리아지 라벨, 도메인 문서). `AGENTS.md`의 `## Agent skills` 절이 가리킨다.

## 합의된 방향 (요구사항 문서 밖)
- 구조: 배포 단위별 최상위 폴더(backend / web / extension / infra). 공유 TS 패키지는 실제로 중복이 생길 때 추가한다.
- 배포: GitHub Actions에서 이미지 빌드 → ECR → EC2가 pull(docker compose). OIDC, SSM Parameter Store를 쓴다. 웹은 S3 + CloudFront.
- 테스트: 배포 이미지에서 뺀다(`.dockerignore`, dev 의존성). 위치(`backend/tests/` 또는 앱별 `tests/`)는 뼈대를 만들 때 하나로 정한다.
- Terraform: 첫 배포가 필요할 때 `infra/terraform/`(모듈 없이 시작)으로 ECR + OIDC부터 붙인다. tfstate는 커밋하지 않는다. 운영용 `compose.prod.yaml`(이미지 digest 고정)과 `nginx/`도 `infra/`에 둔다.

## 현재 레포 상태
새로 시작한 레포다. 이전 MVP 코드는 `MinGyu-Kim0/dragram-mvp`(아카이브)에 있다.
backend·web·extension 뼈대와 CI(`.github/workflows/ci.yml`)가 있다. 기능 코드는 아직 없다. 폴더별 명령은 각 폴더의 `AGENTS.md`에 있다.
이슈 템플릿과 `infra/`(운영 compose, nginx, Terraform)는 아직 없다. `infra/`는 첫 배포 때 만든다.
작업은 `CONTRIBUTING.md`대로 `dev`에서 브랜치를 만들어 PR로 합친다.

## 다음 단계
1. AI 코드 리뷰는 Codex(ChatGPT GitHub 연동)가 PR을 열 때 자동으로 단다. `AGENTS.md`의 `Review guidelines`와 `CONTRIBUTING.md`의 "코드 리뷰" 절(등급·`[권장]` 기준, "CI의 AI 리뷰" 표현)을 서로 맞춘다.
2. ~~grill-with-docs로 첫 기능 단위를 정한다. 문서 간 모순도 이때 정리한다.~~ 완료. 결과는 `docs/design-decisions.md` 28절과 ADR 0003.
3. to-spec → to-tickets → implement(tdd + code-review) → retro.
4. 화면 작업 전에 `DESIGN.md` §7 미정 항목(특히 분석 시작 방식, 루비 켜기/끄기)을 사용자와 정한다.

## 주의
- 합의되지 않은 내용을 결정처럼 기록하지 않는다. 모르면 묻는다.
- 수치·사전 데이터 예시는 실제 데이터로 확인한 뒤 말한다.
- 외부 검토(Codex 등) 결과는 바로 반영하지 말고 사용자에게 먼저 묻는다.
