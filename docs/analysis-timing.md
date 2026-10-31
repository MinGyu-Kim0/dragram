# 분석 시간 기록과 비교 절차

분석이 느릴 때 큐에서 기다린 시간인지 LLM이 처리한 시간인지 나눠 보기 위한 기록이다(#216). 백엔드와
작업자가 표준 오류에 한 줄에 JSON 하나씩 남긴다(`analysis.timing` 로거). 기존 식별자·시간·토큰 수·
오류 코드만 싣고, 원문·프롬프트·모델 응답·인증 비밀은 싣지 않는다.

## 기록 종류

시간은 모두 초이고, 이르지 못한 단계는 `null`이다. 받지 못한 토큰 수도 `null`이다(0으로 채우지
않는다). 한 프로세스 안의 시간은 단조 시계로 잰다. 다른 프로세스 사이의 시간은 큐 대기 하나뿐이고, DB에
남은 선점 시각과 작업 시작 시각(벽시계)으로 잰다.

### `analysis_job`: 작업자가 실행한 분석 작업 하나

작업이 공유돼도 한 번만 남는다. 작업 시간은 이 기록에서만 센다.

| 칸 | 뜻 |
| --- | --- |
| `analysis_id`, `attempt` | 분석 행 ID와 시도(선점 시각). 요청 기록과 같은 값이다 |
| `request_id` | 선점한 요청의 사용 기록(request 행) ID |
| `worker` | 실행한 작업자 프로세스(`호스트:PID`). 한 실행에서 서로 다른 값의 수가 실제로 일한 작업자 수다 |
| `queue_wait_s` | 요청이 선점한 시각 → 작업자가 작업을 시작한 시각 |
| `translation_s` | 작업 시작 → 검증한 번역을 알린 때 |
| `first_response_s` | 작업 시작 → 첫 LLM 스트림을 끝까지 받은 때 |
| `total_s` | 작업 시작 → 작업이 끝난 때(저장·한국어 뜻 만들기 포함, 실패 포함) |
| `result`, `error` | `done`, `failed`(+오류 코드), `skipped`(다시 선점돼 버린 옛 작업) |

### `llm_call`: LLM 호출 하나

사용 기록의 llm 행을 남길 때 함께 남긴다. 분석 작업 밖의 호출(재판정, 접속 형태)도 남는다.
재판정(패턴 세트 버전이 올라 캐시 문장을 다시 매칭하는 경로)은 이 기록만 남고 `analysis_job`·
`analysis_request`는 없다. 이번 범위는 새 문장의 분석 경로다.

| 칸 | 뜻 |
| --- | --- |
| `request_id`, `llm_usage_id`, `analysis_id` | 요청의 request 행, 이 호출의 llm 행, 분석 행 |
| `purpose` | 호출 목적(`first_response`, `reask`, `example_rewrite`, `word_gloss` 등). 첫 호출 밖은 보조 호출이다 |
| `model`, `reasoning_effort` | 응답한 모델과 이때의 추론량 설정 |
| `attempt`, `success` | 시도 차수(일시 오류로 다시 보내면 2)와 성공 여부 |
| `seconds` | 보내기 시작 → 응답을 끝까지 받거나 실패한 때. 첫 호출(스트림)은 받는 도중 작업자가 번역·판정을 검증하고 알리는 시간도 들어간다 |
| `input_tokens`, `cached_input_tokens`, `output_tokens` | 공급자가 알린 사용량. 받지 못했으면 `null` |

### `analysis_request`: 분석 요청 하나

요청이 기다린 시간만 잰다. 시작은 분석 API가 요청을 받은 때다.

| 칸 | 뜻 |
| --- | --- |
| `role` | `cache`(캐시 응답), `saved`(그사이 저장된 결과), `claimed`(선점해 작업을 넣음), `joined`(다른 요청의 작업에 붙음) |
| `request_id`, `analysis_id`, `attempt` | 이 요청의 request 행, 분석 행, 기다린 시도 |
| `translation_s`, `analysis_s` | 요청 시작 → translation 이벤트, analysis 이벤트를 보낸 때 |
| `total_s` | 요청 시작 → 응답이 끝난 때 |
| `result`, `error` | `done`, `error`(+오류 코드), `timeout`(대기 상한), `closed`(끝나기 전에 연결이 끊김) |

캐시 응답(`cache`, `saved`)은 LLM을 부르지 않으므로 `analysis_job`·`llm_call`이 없다.

## 기록 모으기

```bash
docker compose logs --no-log-prefix --since 30m backend worker | grep '^{"event"' > timing.jsonl
```

- `--no-log-prefix`: 줄 앞의 서비스 이름을 빼 JSON만 남긴다.
- `--since 30m`: 비교 실행을 한 시간대만 읽는다.
- `grep '^{"event"'`: 시간 기록 줄만 고른다.

같은 분석은 `analysis_id`와 `attempt`로, 같은 요청의 호출은 `request_id`로 묶는다.

## 비교 절차

한 번에 변수 하나만 바꾼다. 나머지(모델, 문장 세트, 캐시 상태, 반복 횟수)는 그대로 둔다.

1. 평가 문장 세트를 정한다. 관리자가 직접 쓴 문장만 쓰고, 사용자 원문은 쓰지 않는다.
2. 캐시를 맞춘다. LLM 시간을 재려면 세트의 분석 행이 없거나 다시 분석해야 하는 상태여야 한다
   (`role`이 `claimed`가 아니면 캐시를 맞추지 못한 것이다).
3. 실행 구성을 실행 기록으로 남긴다. 모델·추론량은 `llm_call`의 `model`·`reasoning_effort`에서,
   작업자 수는 `analysis_job`의 서로 다른 `worker` 수에서 읽는다. 추론량은 `.env`에 두지 않으면
   `low`다(#217). 작업이 적으면 한 작업자가 모두 가져갈 수 있어 관찰한 작업자 수는 하한이다. 그래서
   실행할 때 띄운 작업자 수(`docker compose ps worker`)도 함께 적는다.
4. 세트를 정한 횟수만큼 요청하고, 위 명령으로 기록을 모은다.
5. 아래 양식을 채운다.

- **추론량만 바꾸는 비교**: 작업자 1개, 문장을 하나씩(앞 요청이 끝난 뒤 다음 요청) 보낸다. 큐 대기가
  섞이지 않아 `first_response_s`·`total_s`가 LLM 처리 시간을 보여 준다. `.env`의
  `OPENAI_REASONING_EFFORT`를 바꾸면 백엔드와 작업자 둘 다 다시 띄워야 적용된다
  (`docker compose up -d backend worker`).
- **작업자 수만 바꾸는 비교**: 추론량을 고정하고 여러 문장을 한꺼번에 보낸다. `queue_wait_s`와 요청의
  `translation_s`·`total_s`를 본다. 작업자 수를 바꾸는 방법은 #218에서 정한다.

### 비교 결과 양식

| 항목 | 값 |
| --- | --- |
| 날짜·커밋 | |
| 모델 / 추론량 | (`.env`에 명시했는지도 적는다) |
| 작업자 수(띄운 수 / 관찰한 수) | |
| 캐시 상태 | (모두 미캐시 / 섞임) |
| 문장 수 · 입력 길이 또는 `input_tokens` | |
| 반복 횟수 | |
| 성공 / 실패 수 | (`analysis_job`의 `result`) |
| `queue_wait_s` 중앙값 / 최댓값 | |
| 작업 `translation_s` 중앙값 / 최댓값 | |
| 작업 `first_response_s` 중앙값 / 최댓값 | |
| 작업 `total_s` 중앙값 / 최댓값 | |
| 요청 `translation_s` · `total_s` 중앙값 | |
| 보조 호출 목적별 횟수 · `seconds` 중앙값 | |
| 실제 모델 / 모의 | |

## 기준 기록 (2026-11-01, #216)

| 항목 | 값 |
| --- | --- |
| 실행 구성(로컬) | 모델 `gpt-6-luna`, 추론량 `low`(`.env`), `compose.yaml`의 worker 서비스 1개 |
| 실제 모델 측정 | **미측정**. 유료 API를 부르지 않았다. 속도와 분석 품질은 검증하지 않았다 |
| 모의 LLM 검증 | 실제 분석 API·PostgreSQL·Redis·RQ 작업자와 가짜 시계로 기록의 의미를 확인했다(`backend/tests/analysis/test_timing.py`). 정상 분석에서 번역 2초, 첫 응답 완료 7초로 돌린 가짜 시계가 `translation_s=2`, `first_response_s=7`, `total_s=7`로 남았다. 실패 두 경로, 공유 작업, 캐시 응답도 확인했다. 이 값은 모의 결과이며 실제 지연 시간이 아니다 |
