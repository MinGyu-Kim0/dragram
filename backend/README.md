# 백엔드 구조

Python 3.14와 Django를 사용한다. `config/`는 설정·전체 URL·상태 확인을, `apps/`는 기능 코드를 소유한다.

| 위치 | 현재 책임 |
| --- | --- |
| `apps/accounts/services.py` | 기존 로컬 사용자 조회·생성 |
| `apps/library/text.py` | 문장 정규화·해시 |
| `apps/library/views.py` | 저장한 문장 목록 |
| `apps/grammar/services.py` | 기존 문법 항목 조회·생성 |
| `apps/analysis/morphology.py` | SudachiPy 형태소 분석 |
| `apps/analysis/llm.py` | 기존 LLM 요청·응답 처리 |
| `apps/analysis/services.py` | 분석 결과 검증·저장 |
| `apps/analysis/serializers.py` | 클라이언트에 제공하는 분석 응답 |
| `apps/analysis/views.py` | 기존 동기 분석 API |
| `apps/reviews/`, `apps/jobs/` | 후속 구현의 책임 명세 |

## 데이터 호환성

현재 모델과 기존 마이그레이션은 `core/models.py`, `core/migrations/`에 유지한다.
`AUTH_USER_MODEL = "core.User"`, 앱 라벨과 테이블 이름도 유지한다.
따라서 이 구조 변경에 DB 초기화나 데이터 이전은 필요하지 않다.

현재 기능 앱은 `core.models`를 사용한다. 모델을 기능별 앱으로 이동하는 작업은
사용자 모델·외래 키·content type·권한·기존 데이터의 이전을 검증하는 별도 변경으로 진행한다.
기존 마이그레이션을 삭제하거나 새 앱의 초기 마이그레이션으로 덮어쓰지 않는다.

## 의존 방향

- 분석 API는 계정·개인 자료·공용 문법 기능을 사용한다.
- 자료함의 현재 목록은 분석 응답 직렬화를 재사용한다.
- 문법 생성 서비스는 분석 모듈을 가져오지 않는다.
- 모든 API 응답 경로는 기존 `/api/health/`, `/api/sentences/`,
  `/api/sentences/analyze/`를 유지한다.

## 테스트

`apps/analysis/tests/`는 형태소·LLM 연동을 검증하고,
`tests/integration/`는 API·저장·재사용·자료함 조회를 함께 검증한다.

```bash
docker compose run --rm -e OPENAI_API_KEY= backend uv run --frozen python manage.py test
docker compose run --rm backend uv run --frozen python manage.py makemigrations --check --dry-run
```

`core`만 지정하면 분리된 테스트를 놓칠 수 있으므로 전체 테스트를 실행한다.
실제 외부 LLM 호출은 테스트에서 대체한다.
