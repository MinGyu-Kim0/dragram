# backend

Django + DRF + PostgreSQL. Python 3.14, 패키지는 uv로 관리한다.

## 명령
DB가 필요한 명령은 루트에서 compose로 실행한다(`backend`의 개발용 이미지에 테스트 도구가 들어 있다).
- 서버 실행: `docker compose up -d` → `http://localhost:8000/api/health/`
- 테스트: `docker compose run --rm backend pytest`
- 마이그레이션 생성: `docker compose run --rm backend python manage.py makemigrations`

DB가 필요 없는 명령은 `backend/`에서 바로 실행한다.
- 의존성 추가: `uv add <패키지>`, 테스트·개발 도구는 `uv add --dev <패키지>`. `uv.lock`도 함께 커밋한다. 바꾼 뒤에는 `docker compose build backend`.
- 포맷·린트: `uv run ruff format .` → `uv run ruff check .`

## 규칙
- 테스트는 `tests/`에 둔다. 배포 이미지(`Dockerfile`의 `prod` 대상)에는 `.dockerignore`로 빠진다.
- 설정값은 `config/settings.py`에서 환경 변수로 읽는다. 비밀값을 코드나 `compose.yaml`에 쓰지 않는다(`compose.yaml`의 값은 개발 전용).
- DB는 PostgreSQL만 쓴다. SQLite로 대신하지 않는다.
- API 오류 응답은 `raise BusinessError(<도메인>Error.<이름>, "로그용 사유")`로 만든다. 뷰에서 오류 `Response`를 직접 만들지 않는다. 오류 코드는 `errors/<도메인>.py`에 `error_domain("<도메인>", {"<이름>": 상태 코드})`로 정의한다. 코드(`ANALYSIS:FAILED`)와 상태 코드는 클라이언트와의 약속이다. 사유는 로그에만 남고 응답에는 나가지 않으며, 원문을 담지 않는다. `errors/`는 도메인 모듈을 import하지 않는다.
- 외부 라이브러리 경계(SudachiPy, OpenAI 등)에서는 그 라이브러리의 예외만 잡아 `BusinessError`로 바꾼다. `except Exception`으로 우리 코드의 버그를 숨기지 않는다.
