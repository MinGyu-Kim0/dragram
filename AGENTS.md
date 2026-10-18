# Dragram

사용자가 직접 고른 일본어 글에서 드래그한 문장을 분석해, 그 사람에게 필요한 문법·단어·한자를 배우게 하는 크롬 확장.

모노레포. 최상위 폴더는 따로 배포되는 단위로 나눈다.
- `backend/`: Django + DRF + PostgreSQL. SudachiPy로 형태소를 분석하고 OpenAI를 호출한다.
- `web/`: React + Vite + TypeScript 웹페이지(내 일본어, 학습 카드, 작문 평가)
- `extension/`: 크롬 확장(사이드 패널)
- `infra/`: 로컬·운영 compose, 나중에 Terraform

폴더별 규칙은 그 폴더의 `AGENTS.md`에 둔다(폴더를 만들 때 함께 만든다).

## 먼저 읽을 것
- 용어가 낯설거나 이름을 지을 때 → `GLOSSARY.md`. 코드·커밋·이슈에 이 용어를 그대로 쓴다.
- 기능 범위·수용 기준 → `docs/requirements.md`
- 테이블·칼럼 → `docs/schema/schema.md`
- "왜 이렇게 정했지?" → `docs/design-decisions.md`(시간순, 뒤 절 우선), `docs/adr/`
- 화면·색·문구 → `DESIGN.md`
- 코드 리뷰 기준 → `CODING_STANDARDS.md`

## 불변식 (모든 변경에서 지킨다)
- 공용 테이블에는 문장 해시·구간 위치·ID·번역만 둔다. 사용자 원문은 `user_sentence`에만 두고, 본인 `user_id`로만 조회한다. Django admin에도 원문을 노출하지 않는다.
- 공용 예문(`example_ja`, `test_cases`)은 LLM이나 관리자가 새로 쓴 문장으로만 채운다.
- LLM 응답은 서버가 검증한 뒤 저장한다. 구간은 서버가 계산하고, 자리표시자(⟨N1⟩ 등)가 모두 남았을 때만 공용 캐시에 넣는다.
- LLM이 만든 지식(용법·뜻)은 승인 전까지 '미검수'로 저장하고 화면에 표시한다. 미검수가 검수처럼 보이면 안 된다.

## 작업 방식
속도보다 신중함을 우선한다. 사소한 작업은 판단껏 줄인다.

**코딩 전에 생각한다**
- 가정을 밝힌다. 애매하면 멈추고, 무엇이 애매한지 말한 뒤 묻는다. 문서에 답이 있으면 그걸 따른다.
- 해석이 여러 개면 하나를 조용히 고르지 말고 나열한다. 더 단순한 방법이 있으면 제안한다.
- 합의되지 않은 내용을 결정처럼 문서에 적지 않는다.

**목표로 실행한다 (TDD)**
- 작업을 검증 가능한 목표로 바꾼다.
  - 기능 추가 → 실패하는 테스트를 먼저 쓰고 통과시킨다.
  - 버그 수정 → 재현 테스트를 먼저 쓰고 통과시킨다.
  - 리팩터링 → 전후로 테스트가 통과한다.
- 여러 단계 작업은 시작 전에 계획을 적는다.
  ```
  1. [단계] → 검증: [확인 방법]
  2. [단계] → 검증: [확인 방법]
  ```
- 끝났다고 말하기 전에 테스트를 실제로 돌린다. 돌리지 못했으면 그렇다고 말한다.

## Git
- `main`과 `dev`에 직접 커밋하지 않는다. `dev`에서 작업 브랜치를 만들고 PR로 `dev`에 합친다. 병합은 사용자가 한다.
- 브랜치 이름, 커밋, PR 작성법은 `.github/CONTRIBUTING.md`를 따른다.

## Agent skills

### Issue tracker
이슈는 GitHub Issues(`MinGyu-Kim0/dragram`)에서 `gh` CLI로 관리한다. `docs/agents/issue-tracker.md` 참고.

### Triage labels
기본 라벨 다섯 개를 그대로 쓴다(`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). `docs/agents/triage-labels.md` 참고.

### Domain docs
single-context: 루트 `GLOSSARY.md` + `docs/adr/`. `docs/agents/domain.md` 참고.

---
작업 방식은 forrestchang/andrej-karpathy-skills(MIT)를 참고했다.
