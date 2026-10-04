# Dragram

## 디렉토리 구조

```text
backend/
  config/                 Django 설정, URL, 상태 확인
  apps/
    accounts/             로컬 계정 기능
    grammar/              문법 항목 조회·생성
    library/              문장 자료함과 입력 정규화
    analysis/             형태소·LLM 분석, 검증, 응답
    reviews/              후속 FSRS 구현의 책임 명세
    jobs/                 후속 작업·복구·예산 구현의 책임 명세
  core/                   기존 DB 모델·마이그레이션 유지
  tests/integration/      기능 간 API·데이터 흐름 검증
frontend/src/
  app/                    화면 구성과 스타일
  features/library/       저장한 문장 조회 화면
  api.ts                  API 통신
extension/
  src/                    확장 프로그램 JavaScript
  tests/                  Chrome 진입점·문장 분리 검증
  manifest.json           확장 등록
  popup.html              팝업 화면
infra/
  compose.dev.yaml        로컬 서비스 정의
  README.md               운영·백업·배포 구성의 추가 위치
.github/workflows/        CI
compose.yaml              로컬 실행 진입점
```

[백엔드 책임과 데이터 호환성](backend/README.md) ·
[인프라 구성과 운영 경계](infra/README.md) ·
[확장 프로그램 설치](extension/README.md)

현재 동기 분석 API와 로컬 모드 동작은 유지한다.
비동기 Job, 공용 지식 검수, FSRS, 운영 배포는 구조만 정한 후속 작업이다.
문법 검색은 PostgreSQL로 시작하며 벡터 검색은 필요성이 검증된 뒤 추가한다.

## 로컬 개발

Docker Compose 2.24.0 이상에서 저장소 루트를 기준으로 실행한다.

```bash
docker compose up --build
```

루트 Compose가 `infra/compose.dev.yaml`을 포함한다.
기존 서비스·볼륨 이름과 루트 `.env` 위치를 유지하므로 구조 변경에 DB 초기화는 필요하지 않다.

## CI

GitHub Actions는 브랜치 push와 Pull Request에서 다음을 검사한다.

- 백엔드: Docker 이미지 빌드, PostgreSQL 준비, Django 설정·마이그레이션 누락 검사,
  기능별 테스트와 API 통합 테스트.
- 프론트엔드: Node.js 22에서 `npm ci` 후 TypeScript 검사와 Vite 빌드.
- 확장: Node.js 기본 테스트 도구로 manifest·팝업 스크립트 경로와 문장 분리 확인.

Actions의 **CI** 워크플로에서 수동 실행할 수도 있다.
이미지 게시와 운영 서버 배포는 아직 포함하지 않는다.

## PR·Issue 작성

저장소 템플릿에 맞춰 한국어로 작성한다. [작성 안내](.github/CONTRIBUTING.md)를 참고한다.
개발 PR의 대상은 `dev`이며 병합은 사용자가 직접 수행한다.
