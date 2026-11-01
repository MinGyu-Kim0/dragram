# DB 스키마 (PostgreSQL)

원본: `erd.json`(ERDCloud 스냅샷). 이 문서는 그 파일에서 생성했다. 결정 근거는 `../design-decisions.md` 참고.

> 설계 시점 스냅샷이다. 구현을 시작하면 Django 모델과 마이그레이션이 기준이고, 이 문서는 바뀐 부분을 손으로 맞춘다.
> design-decisions 28절 변경(`grammar_pattern.status`, `span_match.state` 값)과 33절 1의 탁음화 매핑 변경(`grammar_pattern.morpheme_key`, `pattern_morpheme.lemma` 설명), 41절의 재매칭(`sentence_analysis.matcher_version` 설명, `span_match` 부분 유일성 제약), 42절의 회화체 연결(`grammar_pattern.register`·`variant_of` 설명과 CHECK), 43절의 회화체 연결 때 용법 병합(`grammar_pattern.variant_of`·`usage_closed`, `grammar_usage.pattern_id`, `span_match.analysis_id`·`usage_id`·`candidates`·`alternatives` 설명), 44절의 구성 문법 표시(`grammar_pattern.show_parts` 설명), 45절의 판별 규칙(`usage_rule` 칼럼과 설명, `span_match.decided_by`·`rule_id`·`basis_revision` 설명과 CHECK), 49절의 로그인(`users` 칼럼, `extension_token` 테이블, `usage_log.user_id` 설명), 50절의 문장 단어(`sentence_analysis.word_spans` 칼럼, `sense_ids` 설명), 51절의 큐·작업자(`sentence_analysis.processing_translation_ko` 칼럼, `status`·`generation` 설명, `usage_log.analysis_id` 설명), #93 트리아지와 구현(`user_sentence.original_hash` 타입과 설명, `analysis_id`·`selected_start`·`selected_end`·`last_analyzed_at` 설명), #136의 이름 지정(`designated_name` 테이블), #152의 대응 표현(`grammar_usage.korean_equivalent`·`korean_equivalent_filled`·`korean_equivalent_status` 칼럼, `usage_log.purpose`의 usage_fill, #151의 기능 태그(`grammar_usage.function_tags`·`function_tags_filled`·`function_tags_status`), #177의 평가 세트(`eval_sentence`·`eval_run`·`eval_result`·`eval_item` 테이블), #257의 약관 동의(`users.terms_version`·`privacy_version`·`terms_agreed_at`), #221의 매칭 정정(`match_correction` 설명, `span_match.decided_by`의 admin)은 이 문서에만 반영했고 `erd.json`에는 아직 반영하지 않았다.
> `grammar_pattern`, `pattern_morpheme`, `grammar_usage`, `span_match`, `pattern_set_version`은 #35에서 그때 쓰는 칼럼만 만들었다. 나머지 칼럼(승인·자동 승인, 판 번호, 규칙, 회화체, 대안 해석, confidence 등)은 그 칼럼을 쓰는 하위 티켓에서 일반 마이그레이션으로 더한다(design-decisions 32절). 회화체 칼럼(`register`·`variant_of`)은 #63에서, `show_parts`는 #65에서, `usage_rule`과 `span_match.rule_id`는 #55에서, `function_tags`·`function_tags_filled`·`function_tags_status`는 #151에서 더했다.

## users — 사용자

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| google_sub | 구글 계정 식별자 | varchar(255) | Y |  | Google OAuth sub, UNIQUE. 같은 사람인지는 이 값으로 판단한다. `createsuperuser` 관리자와 개발 로그인 사용자는 NULL |
| username | 사용자 이름 | varchar(150) |  |  | `AbstractUser` 칸, UNIQUE. Google 사용자는 `google-<무작위>`(sub는 255자까지 될 수 있어 넣지 않음), 개발 로그인은 `dev:<이메일>` |
| email | 이메일 | varchar(254) |  |  | UNIQUE 아님(같은 사람은 google_sub로 판단, 이메일은 바뀌거나 겹칠 수 있다). Google 로그인 때마다 갱신 |
| is_staff | 관리자 여부 | boolean |  |  | 패턴·용법 승인 권한(Django admin). 관리자가 admin에서 준다 |
| is_active | 사용 가능 | boolean |  |  | 거짓이면 로그인(`AUTH:ACCOUNT_DISABLED`)과 분석 API를 거부한다 |
| date_joined | 가입일시 | timestamptz |  |  | `AbstractUser` 칸 |
| terms_version | 동의한 이용약관 | date | Y |  | 동의한 이용약관의 시행일. 가입하기를 누를 때 서버가 정한다(웹이 보낸 값을 믿지 않는다). 동의 전 계정은 NULL이다(#257) |
| privacy_version | 고지한 처리방침 | date | Y |  | 가입 화면에 보여 준 개인정보처리방침의 시행일. 동의가 아니라 고지한 판의 기록이다(design-decisions 68절). 동의 전 계정은 NULL이다 |
| terms_agreed_at | 약관 동의일시 | timestamptz | Y |  | 가입하기를 누른 시각. 동의 전 계정은 NULL이다 |

`AbstractUser`의 나머지 칸(password, first_name 등)도 있다. Google로 가입한 사용자는 비밀번호를 쓸 수 없다(ADR 0004, design-decisions 49절).

## extension_token — 확장 토큰

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| token_hash | 토큰 해시 | varchar(64) |  |  | 토큰 원본의 SHA-256, UNIQUE. 원본은 발급 응답에만 싣고 저장하지 않는다 |
| user_id | 사용자 ID | bigint |  | → users |  |
| session_key | 발급 세션 | varchar(40) |  |  | 발급한 웹 로그인 세션. 웹 로그아웃이 이 세션이 발급한 토큰을 폐기한다. 인덱스 |
| created_at | 발급일시 | timestamptz |  |  |  |
| last_used_at | 마지막 사용 일시 | timestamptz | Y |  | 한 번도 쓰지 않았으면 NULL. 처음 쓸 때 채우고, 그 뒤에는 날짜가 바뀔 때만 갱신한다. 이 날짜(없으면 발급 날짜)부터 90일째 날까지 쓰고 그 뒤 만료 |
| revoked_at | 폐기일시 | timestamptz | Y |  | 확장 로그아웃, 웹 로그아웃, 같은 세션의 다른 사용자 로그인 때 채운다 |

세션마다 토큰은 많아야 둘이다(쓰던 토큰과 아직 쓰지 않은 새 토큰, design-decisions 49절).

## user_sentence — 분석 기록

> 사용 중단(2026-11-01, #322, ADR 0006): 분석할 때 원문을 더는 저장하지 않는다. 남은 행은 배포 마이그레이션 0030이 지운다(처리방침 2026-11-02판). 테이블을 없앨지는 따로 정한다. 아래는 예전 설명이다.

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| user_id | 사용자 ID | bigint |  | → users | 개인 데이터. 본인만 조회, 탈퇴 시 삭제 |
| original_hash | 원문 해시 | varchar(64) |  |  | 요청으로 받은 원문(정규화 전) 그대로의 SHA-256. UNIQUE(user_id, original_hash). 같은 사용자·같은 원문은 한 문장 upsert로 갱신해 동시 요청도 유일성 위반 없이 끝난다. 숫자만 다른 원문(1人/2人)도 따로 보관 |
| analysis_id | 공용 분석 ID | bigint |  | → sentence_analysis | sentence_analysis.id 참조(FK). 공용 분석 행을 지우지 못하게 막는다(PROTECT). 지금 공용 분석을 지우는 코드는 없고, 지우게 되면 개인 기록을 어떻게 할지 그때 정한다(#93 구현, 확인 필요). 여러 사용자·숫자만 다른 원문이 같은 공용 분석을 가리킴. 해시는 조인해서 조회. 인덱스 있음(내 일본어 조회용). 정규화 규칙 변경 시 원문별로 새 키를 계산해 해당 분석이 준비되면 analysis_id를 재연결 |
| original_text | 원문 | text |  |  | 정규화 전 원문. 개인 테이블에만 저장, 카드 예문 표시용 / 개인 원문, 본인만 조회, Django admin 미노출 |
| name_readings | 이름 읽기 | jsonb |  |  | 기본값 `[]`. 보충한 이름 카드의 `{start, end, reading, reading_ko}` 목록. 위치는 original_text의 UTF-16 반열린 구간, reading은 가나, reading_ko는 한글 읽기다. 변환할 수 없는 이름은 제외한다. 개인 기록에만 저장하며 캐시 재조회·재분석·재매칭 때 해당 결과로 교체한다. 기존 기록은 다음 조회 때 채운다(0024 마이그레이션, design-decisions 63절). erd.json에는 미반영 |
| selected_start | 드래그 시작 위치 | integer |  |  | original_text 코드포인트 기준. 실제로 드래그한 범위(문장 끝까지 자동 확장과 별도로 강조 표시). 읽는 곳이 없어 #93에서는 넣지 않는다. FR-M12처럼 필요해지면 별도 이슈로 더한다(2026-10-25 #93 트리아지) |
| selected_end | 드래그 끝 위치 | integer |  |  | 반열린 구간 [start, end). selected_start와 같이 #93에서는 넣지 않는다 |
| created_at | 처음 분석일시 | timestamptz |  |  |  |
| last_analyzed_at | 마지막 분석일시 | timestamptz |  |  | 같은 원문을 다시 분석하면 행을 새로 만들지 않고 갱신. 응답에 분석 결과가 나갔고 공용 분석 행에 저장된 결과가 있을 때만 저장·갱신한다(#93 트리아지). 저장이 실패(DB 오류)해도 보낸 응답은 그대로 두고, 원문 없이 analysis_id와 오류 종류만 로그로 남긴다(#93 구현, 확인 필요) |

## user_sentence_source — 분석 출처

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| user_sentence_id | 분석 기록 ID | bigint |  | → user_sentence | UNIQUE(user_sentence_id, url_hash). 출처는 사용자별로만 보관 |
| source_url | 출처 URL | varchar(2048) |  |  | 쿼리 문자열과 프래그먼트를 제거하고 저장 |
| url_hash | URL 해시 | char(64) |  |  | source_url SHA-256. 긴 URL에 UNIQUE를 걸기 위한 열쇠 |
| source_title | 페이지 제목 | varchar(255) | Y |  |  |
| first_seen_at | 처음 본 일시 | timestamptz |  |  |  |
| last_seen_at | 마지막 본 일시 | timestamptz |  |  | 10분 내 재방문은 이 값만 갱신. 새 출처 연결은 누락 없이 행 추가 |

## designated_name — 지정한 이름

사용자가 단어 카드의 표기를 이름으로 지정한 것(이름 지정, #136). 개인 데이터라 예문(`my_example`)과 같이 본인 user_id로만 조회·수정·삭제하고, Django admin에 등록하지 않고, 로그·usage_log·오류 사유에 표기·읽기를 남기지 않는다. 공용 테이블·공용 캐시·LLM 요청에는 넣지 않는다. 적용은 확장이 단어의 원문 자리로 표층형을 잘라 맞춘다(#136 구현, 확인 필요).

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| user_id | 사용자 ID | bigint |  | → users | 개인 데이터. 본인만 조회, 탈퇴 시 삭제(CASCADE). 사용자당 1000개까지(#136 구현·PR #167 리뷰, 확인 필요) |
| surface | 표기 | varchar(50) |  |  | 원문 토큰의 표층형. UNIQUE(user_id, surface). 같은 표기를 다시 지정하면 행을 늘리지 않고 reading만 바꾼다 |
| reading | 읽기 | varchar(50) | Y |  | 가나만 받아 히라가나로 통일해 저장. 비었으면 NULL(읽기 없음) |
| created_at | 생성일시 | timestamptz |  |  |  |
| updated_at | 수정일시 | timestamptz |  |  |  |

## my_item — 내 일본어 항목

사용자가 사이드 패널 카드에서 추가하거나 '표시 안 함'으로 숨긴 용법·단어 뜻(#322, ADR 0006). 개인 데이터라 본인 user_id로만 조회·수정·삭제하고 Django admin에 등록하지 않는다. 원문은 없다. 사용자당 10,000행 상한.

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| user_id | 사용자 ID | bigint |  | → users | 탈퇴 시 삭제(CASCADE) |
| usage_id | 용법 ID | bigint | Y | → grammar_usage | usage_id와 sense_id 중 하나만 있다(CHECK). UNIQUE(user_id, usage_id). 용법을 합치면 합친 용법으로 옮긴다(추가가 숨김보다 앞섬). 용법을 지우지 못하게 PROTECT |
| sense_id | 단어 뜻 ID | bigint | Y | → word_sense | UNIQUE(user_id, sense_id). 뜻이 지워지면 함께 지운다(CASCADE) |
| state | 상태 | varchar(30) |  |  | added(추가, 웹 내 기록에 보임) / hidden(표시 안 함, 사이드 패널에서 접음) |
| created_at | 등록일시 | timestamptz |  |  |  |
| updated_at | 변경일시 | timestamptz |  |  | 웹 목록은 최근 바꾼 순 |

## my_example — 예문

사용자가 카드를 추가한 뒤 예문으로 저장하기로 고른 문장(#322). 개인 원문은 이 테이블에만 둔다. 본인 user_id(항목의 사용자)로만 조회하고 Django admin·로그·공용 테이블에 남기지 않는다. 항목당 20개 상한.

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| item_id | 항목 ID | bigint |  | → my_item | 항목을 빼면(해제) 함께 지운다(CASCADE) |
| original_hash | 원문 해시 | varchar(64) |  |  | 원문의 SHA-256. UNIQUE(item_id, original_hash) |
| original_text | 원문 | text |  |  | 사용자가 고른 문장 그대로(분석 원문과 같은 1,000자 상한) |
| highlight_start | 표시 시작 | int | Y |  | 이 예문에서 카드가 가리키는 부분의 시작. 원문 기준 UTF-16 위치이고, 사이드 패널이 받은 카드 위치를 그대로 보낸다. 구간을 저장하기 전 예문(0031 이전)은 NULL |
| highlight_end | 표시 끝 | int | Y |  | 그 부분의 끝(배타). 0 ≤ 시작 < 끝 ≤ 원문 길이를 서버가 검사한다 |
| created_at | 저장일시 | timestamptz |  |  |  |

## usage_log — 사용 기록

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| user_id | 사용자 ID | bigint | Y | → users | 분석 요청과 그 요청의 LLM 호출은 확장 토큰의 주인(#109). 시스템 일괄 작업 호출이면 null. 하루 토큰 한도의 집계 기준(#28, design-decisions 52절) |
| analysis_id | 문장 분석 ID | bigint | Y | → sentence_analysis | (구현이 정함, 확인 필요, design-decisions 51절) 선점한 분석 행에 처음부터 잇는다. 새 문장도 LLM을 부르기 전에 처리 중 행을 먼저 만들어, 실패한 시도의 기록도 그 행에 이어진다. 재매칭은 기존 분석 행에 잇는다 |
| kind | 기록 종류 | varchar(30) |  |  | request(분석 요청, 경로를 정할 때 1행) / llm(LLM 호출, 호출마다 저장 트랜잭션 밖에서 바로 1행. 마감이 지나 보내지 않은 호출은 남기지 않음. 기록 시점은 구현이 정함, 확인 필요). 원문은 저장하지 않음 |
| path | 처리 경로 | varchar(30) | Y |  | request일 때: cache(패턴 세트 버전이 최신인 캐시 분석을 그대로 보냄) / db(캐시 분석을 다시 매칭했고 LLM 없이 확정) / llm(LLM을 부름: 새 문장, stale 재분석, 재매칭 재판정). 처리 중 작업에 붙은 요청도 현재 llm이며, 이 분류는 FR-M01 전에 확인할 구현 동작(design-decisions 51절) |
| purpose | 호출 목적 | varchar(30) | Y |  | llm일 때: first_response(번역+판별+새 문법 찾기 1회 호출) / reask(용법 재질문·해석 갈림 근거 재질문) / example_rewrite(원문을 베낀 새 예문 다시 쓰기) / rematch_judge(패턴 세트 버전이 올라 다시 매칭한 캐시 문장의 새 판별 대상 구간 판정) / word_gloss(JMdict 뜻의 한국어 뜻 생성, 문장 없음(#97). 사전에 없는 단어의 2단계(뜻 고르기·새 뜻 생성, 문장 있음)도 이 목적이다(#134)) / kanji_gloss(한자 한국어 뜻) / pattern_connection(공용 패턴의 접속 형태 생성, 원문 없음, #229) / usage_fill(채우기 명령 `fill_usages`가 용법을 묶어 대응 표현을 묻는 호출, 문장 없음, user_id·analysis_id NULL(#152)) |
| model | 모델명 | varchar(255) | Y |  |  |
| input_tokens | 입력 토큰 수 | integer | Y |  |  |
| cached_input_tokens | 캐시된 입력 토큰 수 | integer | Y |  | 프롬프트 캐싱 효과 확인용(cached_tokens) |
| output_tokens | 출력 토큰 수 | integer | Y |  |  |
| success | 성공 여부 | boolean |  |  | request: 그 경로의 결과를 오류 없이 냈는가(재매칭 대체 응답과 분석 중 영향 범위가 바뀌어 저장을 되돌린 요청은 false). llm: 쓸 수 있는 응답을 받았는가(SDK 오류·잘린 응답·JSON 아님·LLM 스트림 중단은 false, 받은 뒤 서버 검증 거부는 true. 구현이 정함, 확인 필요). 패널 연결이 끊겨도 작업자는 계속 실행한다. design-decisions 46·51절 |
| attempt | 시도 차수 | smallint | Y |  | llm 행의 첫 호출은 1, 아무것도 받기 전 일시 오류로 요청 마감 안에서 한 번 다시 보낸 호출은 2. 타임아웃·응답 검증 실패·조각을 받은 스트림은 다시 보내지 않음(#99, design-decisions 51절 5, requirements FR-A18) |
| created_at | 기록일시 | timestamptz |  |  |  |

## admin_action_log — 관리자 작업 이력

아직 만들지 않았다. 매칭 정정의 작업 기록은 이 테이블 대신 Django admin 기록(`django_admin_log`)에 '정정: 전 → 후'와 상태 변경으로 남긴다(2026-11-01 사용자 결정, design-decisions 70절).

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| actor_id | 처리자 ID | bigint |  | → users |  |
| target_type | 대상 종류 | varchar(30) |  |  | usage / pattern / rule / correction / analysis / word |
| target_id | 대상 ID | bigint |  |  | 대상 테이블의 id |
| action | 작업 | varchar(30) |  |  | approve / reject / revert / close / reopen / correct / reanalyze / activate |
| before_value | 변경 전 값 | jsonb | Y |  |  |
| after_value | 변경 후 값 | jsonb | Y |  |  |
| created_at | 처리일시 | timestamptz |  |  |  |

## word — 단어

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| dictionary_form | 원형 | varchar(255) |  |  | 대표 표기(표시용). 조회는 forms. 뜻은 word_sense. JMdict 적재: 첫 keb, 없으면 첫 reb(구현이 정함, 확인 필요) / 빈 문자열 금지 CHECK(word_display_not_empty, reading과 함께) |
| reading | 읽기 | varchar(255) |  |  | 대표 읽기(표시용). 조회는 readings. 원래 표기 그대로(コーヒー). JMdict 적재: 대표 표기에 쓰는 첫 reb(re_nokanji가 아니고 re_restr가 없거나 대표 표기를 포함), 없거나 가나만 있는 항목이면 첫 reb(구현이 정함, 확인 필요) |
| forms | 모든 표기 | text[] |  |  | JMdict 항목의 모든 한자·가나 표기. GIN. SudachiPy 사전형으로 조회. 사전에 없는 단어는 `[사전형, 히라가나 읽기]`, 둘이 같으면 하나(#134 구현이 정함, 확인 필요) |
| readings | 모든 읽기 | text[] |  |  | 모든 읽기(히라가나 통일). GIN. 비활용어·가나 표기 단어 조회용. 사전에 없는 단어는 `[히라가나 읽기]`(#134 구현이 정함, 확인 필요) |
| is_common | 흔한 단어 | boolean |  |  | ke_pri·re_pri 중 news1·ichi1·spec1·spec2·gai1이 하나라도 있으면 true(구현이 정함, 확인 필요). 후보가 여럿일 때 순서 힌트. 사전에 없는 단어는 false(#134 구현이 정함, 확인 필요) |
| reading_restrictions | 읽기 제한 | jsonb | Y |  | `{읽기: [허용 표기]}`. re_restr: 읽기→허용 표기 목록, re_nokanji 읽기는 `[]`(한자 표기에 쓰지 않음, 구현이 정함, 확인 필요). 표기에 맞는 읽기 표시·후보 거르기용. 대부분 NULL |
| pos | 품사 | varchar(255) |  |  | JMdict 적재: 첫 뜻의 JMdict pos 코드를 `,`로 이은 값(예: `v1,vt`). pos가 없는 뜻은 앞 뜻의 pos를 이어받음(출처 JMdict는 사용자 결정, 값 모양은 구현이 정함·확인 필요, design-decisions 47절). 사전에 없는 단어는 빈 문자열(#134 구현이 정함, 확인 필요) |
| tags | 단어 태그 | text[] |  |  | 영문 코드 배열. 단어 전체 태그(품사·동사 그룹(group1/2/3, 예외 1그룹은 group1 대신 group1_exception)·い/な형용사·고유명사) + 검색용 sense 태그 합집합. GIN. 허용 목록과 JMdict 변환표는 코드 상수(`analysis/jmdict.py`). 단어 전체 태그는 모든 뜻의 JMdict pos에서 만듦(design-decisions 47절). 사전에 없는 단어는 LLM이 허용 목록 안에서 고른 단어 전체 태그만 둔다. 목록 밖 값은 버린다(#134 트리아지). 새 단어에 뜻 태그 합집합을 넣지 않고, 기존 단어에 LLM 뜻을 더할 때도 이 칸을 바꾸지 않는다(#134 구현이 정함, 확인 필요) |
| jmdict_seq | JMdict 항목 번호 | integer | Y |  | UNIQUE. JMdict 항목 1개 = word 1행. 사전에 없는 단어(LLM 생성)면 NULL / 사전에 없는 단어 중복 방지: 부분 UNIQUE(dictionary_form, reading) WHERE jmdict_seq IS NULL (저장 전 가나 정규화, 빈 값 금지, 대표 표기 고정) |
| updated_at | 수정일시 | timestamptz |  |  |  |

## grammar_pattern — 문법 패턴

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| name | 패턴명 | varchar(255) |  |  | 예: 명사+で |
| connection_form | 접속 형태 | varchar(255) | Y |  | 예: 동사 て형 + いる. 문장별 설명이 아닌 공용 문법 지식. 사용자 원문·자리표시자는 저장하지 않음(#229) |
| connection_filled | 접속 형태 채움 여부 | boolean |  |  | 기본 false(기존 패턴). 새 패턴은 첫 LLM 응답에서 함께 채움. true + NULL은 신뢰할 수 있는 공식 없음이며 다시 호출하지 않음 |
| connection_status | 접속 형태 검수 상태 | varchar(30) | Y |  | LLM 값은 pending, 관리자 수정·승인은 approved, 값이 없으면 NULL. 패턴·용법 검수 상태와 별도 |
| connection_started_at | 접속 형태 생성 시작 | timestamptz | Y |  | 별도 생성 작업의 선점 시각. 같은 패턴은 작업을 공유하고 150초 뒤 재시도 가능. 해당 시도만 저장·해제 가능 |
| morpheme_key | 형태소 열 키 | char(64) |  |  | 형태소 행(lemma\|pos1\|pos2\|conj, 아무거나는 *)을 순서대로 이은 문자열의 SHA-256. UNIQUE(morpheme_key). lemma 규칙: 조사·조동사는 SudachiPy dictionary_form(축약형 보존), 동사·형용사 등 내용어는 normalized_form(표기 통일). 탁음화 조건부 매핑: 앞 토큰이 동사이고 활용형이 連用形-撥音便·連用形-イ音便이면 で→て, でる→てる, じゃう→ちゃう, だ→た(だら는 원형이 だ라 함께 처리), どく→とく, じまう→ちまう, でく→てく, じゃ(接続助詞)→ちゃ. 이 규칙 이전에 등록된 패턴은 보정하지 않음(design-decisions 33절 1, 42절 14). 동시 생성은 get_or_create |
| register | 말투 | varchar(20) |  |  | standard / colloquial, 기본 standard. 관리자가 원형에 연결할 때만 colloquial이 되고 해제해도 남음(admin 폼에서 따로 고치지 않음). colloquial이면 '회화체' 배지. colloquial인 패턴은 원형으로 고를 수 없음. variant_of가 있을 때(연결된 회화체)만 원형의 설명·용법을 쓰고, 해제된 회화체는 자기 용법을 씀 / variant_of가 있으면 colloquial(CHECK) |
| usage_closed | 용법 완결 여부 | boolean |  |  | 관리자가 용법이 하나뿐이라고 확인한 패턴. 활용형 조건 검토 필수. 패턴 승인 + test_cases 통과 + 반려되지 않은 용법이 정확히 하나이고 승인 상태일 때만 true. 새 용법 추가(회화체 연결 때의 옮김 포함)·용법 반려 취소·용법이나 패턴의 승인 취소·반려 때 같은 트랜잭션에서 false로 바꾸고 그 패턴의 분석을 stale로. 원형에 연결된 회화체는 원형 승인 + 원형의 반려되지 않은 용법이 승인된 하나뿐이어야 하고, 원형 쪽 위 사건과 연결·해제 때도 false로 바꿈(design-decisions 42절) |
| revision | 패턴 판 번호 | integer |  |  | 용법 완결 여부·형태소 조건·용법 구성이 바뀌면 증가. span_match.basis_revision과 조회 시 비교 |
| show_parts | 구성 문법 표시 여부 | boolean |  |  | 기본 true. 이 패턴이 바깥 구간일 때 그 안에 완전히 들어가는 구성 문법을 하위 박스로 보일지(true) 숨길지(false). 펼쳐 보는 토글은 없음. 바깥 구간에 실제로 매칭된 패턴의 값을 씀(회화체는 자기 값). 표시 전용이라 조회할 때 읽고, 바꿔도 stale·세대 번호·패턴 세트 버전·LLM 호출 없음. 분석 후보와 구성 문법의 span_match는 항상 보존. admin 폼에서 고침(design-decisions 44절) |
| test_cases | 검증 예문 | jsonb |  |  | [{text, should_match}] 성공·실패 예문. '걸리면 안 됨' 예문은 관리자가 admin에서 씀. 승인·용법 완결 패턴은 통과하지 못하게 바꿀 수 없음(먼저 승인 취소). 첫 '걸려야 함' 항목은 등록 때 LLM이 새로 쓴 예문(원문을 베꼈으면 거부: 키 텍스트가 같거나, 원문 전체를 포함하거나, 원문의 연속된 일부를 기준 길이(`EXAMPLE_COPY_LENGTH`, 기본 8자) 이상 포함. 패턴에서 고정한 토큰 글자는 세지 않되, 그 토큰을 사이에 둔 앞뒤 복사는 이어서 셈. 기호·공백을 뺀 형태소가 하나뿐인 원문은 포함만 예외, 같으면 거부. 원문을 베껴 거부되면 한 번 다시 쓰게 함. 200자를 넘는 예문은 쓰지 않음). 전부 통과해야 승인·용법 완결 가능. 새로 쓴 should_match true·false 예문이 각각 1개 이상 있어야 하고 빈 배열은 통과 아님 / LLM·관리자가 새로 쓴 예문만, 사용자 원문 저장 금지(매칭기로 확인 후 저장, 회귀 테스트 겸용) |
| is_active | 활성 여부 | boolean |  |  | 활성화 근거(등록 때 원래 문장 재매칭 통과 + 새로 쓴 should_match 예문 1개 이상 통과, LLM·관리자 예문 모두 인정)가 있고 rejected가 아니면 true. 반려 취소·예문 보완(admin에서 test_cases 저장) 때 서버가 다시 검증. 값이 바뀌거나 활성 패턴의 형태소 조건(pattern_morpheme)이 바뀌면 같은 트랜잭션에서 pattern_set_version.version을 1 올림. false면 매칭에 쓰지 않음 |
| status | 승인 상태 | varchar(30) |  |  | pending / approved / rejected. 형태소 조건의 검수 상태(용법 승인과 별개). LLM이 만든 패턴은 pending으로 생성. 원형에 연결된 회화체 패턴의 미검수 여부도 이 칸으로 판단. 반려 취소는 항상 pending으로 되돌림. 반려·반려 취소 시 이 패턴과 이 패턴을 원형으로 가리키는 회화체 패턴의 분석을 stale로(전이표는 requirements '패턴 매칭 규칙') |
| created_at | 등록일시 | timestamptz |  |  |  |
| variant_of | 원형 패턴 | bigint | Y | → grammar_pattern | 회화체 패턴이 가리키는 원형 패턴(자기 참조, 인덱스). 관리자가 admin 액션으로 연결·해제. 1단계만·체인 금지(원형은 register standard라 variant_of null). 회화체는 자기 용법 없이 원형 용법을 씀. 연결·해제하면 그 회화체 분석을 stale로 만들고, 연결로 매칭 자격이 생기면 pattern_set_version을 올림 / 자기 자신이 아님(CHECK), 연결된 회화체는 반려되지 않은 자기 용법 없음(연결할 때 남은 용법마다 원형 용법으로 합치거나 원형 아래로 옮기고, 대응을 고르지 않으면 연결 거부. 반려 취소 거부로 서버 검증, design-decisions 43절) |

## pattern_set_version — 패턴 세트 버전

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | smallint |  | PK | 항상 1인 한 행만 둔다(CHECK id = 1) |
| version | 현재 패턴 세트 버전 | integer |  |  | grammar_pattern.is_active나 활성 패턴의 형태소 조건이 바뀌거나, 패턴의 매칭 자격(활성 + 후보가 될 용법 1개 이상. 연결된 회화체는 원형의 반려되지 않은 용법)이 거짓에서 참이 되는(용법 반려 취소, 첫 용법 추가, 회화체 연결, 원형 반려 취소) 트랜잭션에서 행을 잠그는 UPDATE … SET version = version + 1로 1 증가. 새 패턴을 등록하는 트랜잭션은 패턴을 morpheme_key 순서로 넣고 이 행은 마지막에 잠근다(동시 등록 교착 방지). 상태 전이·분석 저장·재매칭 저장은 패턴(·용법) → 이 행 → 분석 행 순서로 잠그고, 구간은 분석 행을 잠근 뒤 쓴다. 패턴은 그 패턴을 원형으로 가리키는 회화체까지 한 번에 id 순서로 잠근다. 회화체 연결·해제와 구간을 저장하는 분석은 그보다 먼저 원형 연결 상태 advisory 잠금(연결·해제는 배타, 분석은 공유)을 잡는다(design-decisions 35절, 41절, 42절). sentence_analysis.matcher_version과 비교하는 현재값 |
| updated_at | 수정일시 | timestamptz |  |  |  |

## pattern_morpheme — 패턴 형태소

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| pattern_id | 문법 패턴 ID | bigint |  | → grammar_pattern |  |
| seq | 순서 | smallint |  |  | UNIQUE(pattern_id, seq) |
| lemma | 표제어 | varchar(255) | Y |  | 조사·조동사는 SudachiPy dictionary_form(축약형 보존), 동사·형용사 등 내용어는 normalized_form(표기 통일). 탁음화 조건부 매핑: 앞 토큰이 동사이고 활용형이 連用形-撥音便·連用形-イ音便이면 で→て, でる→てる, じゃう→ちゃう, だ→た(だら는 원형이 だ라 함께 처리), どく→とく, じまう→ちまう, でく→てく, じゃ(接続助詞)→ちゃ. 이 규칙 이전에 등록된 패턴은 보정하지 않음(design-decisions 33절 1, 42절 14). null이면 아무거나(정확히 1토큰) |
| pos1 | 품사 대분류 | varchar(30) | Y |  | null이면 아무거나 |
| pos2 | 품사 중분류 | varchar(30) | Y |  |  |
| conjugation_form | 활용형 | varchar(30) | Y |  | 과거/조건(終止形 vs 仮定形)처럼 구분이 필요한 패턴은 필수 |

## grammar_usage — 용법

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| pattern_id | 문법 패턴 ID | bigint |  | → grammar_pattern | 회화체를 원형에 연결하며 '옮김'을 고르면 원형 패턴으로 바뀜(검수 상태 유지, 원형 조건에 걸리지 않는 example_ja는 NULL). '합침'을 고른 용법은 행을 지움(design-decisions 43절) |
| name | 용법명 | varchar(255) |  |  | 예: で-수단, UNIQUE(pattern_id, name) |
| explanation_ko | 한국어 설명 | text |  |  | LLM이 처음 1회 작성 → 관리자 검수. 공용 재사용 |
| example_ja | 예문 | text | Y |  | LLM·관리자가 새로 쓴 예문만, 사용자 원문 저장 금지. `grammar_pattern.test_cases`의 첫 예문과 같은 검사를 통과해야 저장(소속 패턴에 걸림, 원문 복사 아님, 자리표시자 없음, 200자 이하. design-decisions 34절). 통과하지 못하면 NULL |
| korean_equivalent | 대응 표현 | varchar(100) | Y |  | 이 용법이 한국어로 주로 옮겨지는 표현(용법 일반, 문장별 아님. 예: に-대상 → ~을/를). 마땅한 대응이 없으면 NULL. 새 용법을 만드는 LLM 경로(새 구문·미발견·다시 묻기·재매칭 재판정)가 함께 답하고, 글이 아니거나 빈 값·숫자 자리표시자·100자 초과·문장 전체 인용이면 이 칸만 NULL로 저장(용법 등록은 실패시키지 않음). 관리자는 admin 용법 화면과 패턴 인라인에서 고침(비우면 NULL). 상한 100자는 #152 구현이 정함(확인 필요) |
| korean_equivalent_filled | 대응 표현 채움 여부 | boolean |  |  | 기본 false. 채운 적이 있으면 true라, korean_equivalent NULL이 '대응 없음'인지 '아직 안 채움'인지 가름. LLM 경로·admin 수정·채우기 명령이 true로 둠. 채우기 명령은 false인 행만 채움(조건부 update라 그사이 admin이 쓴 값을 덮지 않음) |
| korean_equivalent_status | 대응 표현 검수 상태 | varchar(30) | Y |  | pending / approved, 값이 NULL이면 NULL. LLM 값은 pending, admin이 쓴 값은 approved. 용법을 승인하면 pending 대응 표현도 함께 approved. 승인된 용법에 나중에 채운 값은 admin 액션 '대응 표현 승인'까지 pending(design-decisions 54절) |
| revision | 용법 판 번호 | integer |  |  | 설명이 아닌 의미 정의가 바뀌면 증가. span_match.usage_revision과 조회 시 비교 |
| function_tags | 기능 태그 | varchar(30)[] |  |  | FunctionTag 코드 배열, 허용 목록(DESIGN §5) 순서·중복 없음. 기본 빈 배열. LLM 답의 목록 밖 값은 서버가 버리고, admin은 목록 밖 값을 저장하지 못함(design-decisions 55절) |
| function_tags_filled | 기능 태그 채움 여부 | boolean |  |  | 채운 적이 있는가. 빈 배열이 '태그 없음'인지 '아직 안 채움'인지 가름. `fill_usages`는 false인 용법만 채움. 기본 false |
| function_tags_status | 기능 태그 검수 상태 | varchar(30) | Y |  | pending / approved. 태그가 없으면 NULL. LLM이 쓴 값은 pending, admin이 고친 값은 approved. 용법을 승인하면 함께 approved. 승인된 용법에 나중에 채운 태그는 admin '기능 태그 승인'까지 pending(태그 줄에 'AI 생성·미검수' 배지 하나) |
| status | 승인 상태 | varchar(30) |  |  | pending / approved / rejected. pending은 'AI 생성·미검수' 배지로 표시, 확정 판별 근거로는 approved만. rejected는 판정·규칙·LLM 후보에서 빼고 응답에도 보이지 않음. 승인은 소속 패턴이 rejected가 아닐 때만(test_cases 조건 없음). 반려 취소는 항상 pending으로 되돌림. 반려·반려 취소 시 이 용법이 속한 패턴과 그 패턴을 원형으로 가리키는 회화체 패턴의 분석을 stale로 |
| approved_via | 승인 방식 | varchar(30) | Y |  | manual / auto. auto는 그림자 모드 검증 후 실제 자동 승인을 켠 뒤에만 |
| approved_by | 승인자 ID | bigint | Y | → users | 자동 승인이면 null |
| approved_at | 승인일시 | timestamptz | Y |  |  |
| would_auto_approve | 자동 승인 예측 | boolean | Y |  | 그림자 모드: 기준상 '승인했을 것' 기록. null=미평가. status는 바꾸지 않음 |
| auto_approve_basis | 자동 승인 예측 근거 | jsonb | Y |  | 판별 일치 횟수, 예문 테스트 결과 등 |
| auto_approve_evaluated_at | 자동 승인 예측일시 | timestamptz | Y |  | 관리자 결정과 비교해 일치율 집계 |
| origin | 등록 경로 | varchar(30) |  |  | llm / admin. llm은 항상 pending(미검수)으로 생성 |
| created_at | 등록일시 | timestamptz |  |  |  |
| updated_at | 수정일시 | timestamptz |  |  |  |

## usage_rule — 판별 규칙

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| usage_id | 용법 ID | bigint |  | → grammar_usage | 조건이 맞으면 이 용법으로 확정. pattern_id(연결된 회화체면 원형) 소속이어야 함(admin 저장·승인 때 DB에서 다시 확인). 지금 구현은 회화체 연결 때 이 용법을 합치면 합칠 원형 용법으로 바꿈(확인 필요, design-decisions 43절·45절) |
| pattern_id | 패턴 ID | bigint |  | → grammar_pattern | 실제 매칭된 패턴의 승인 규칙만 적용(회화체가 원형 용법을 공유해도 규칙은 패턴별) |
| condition | 판별 조건 | jsonb |  |  | 구간 앞뒤 두 토큰까지의 형태소 조건 AND. 예: 앞 명사가 지명이면 で-장소. 지금 구현은 [{position: -2\|-1\|1\|2, lemma, pos1, pos2, pos3, conjugation_form}](비운 칸은 아무거나, 그 자리에 토큰이 없으면 맞지 않음). pos3(품사 소분류)는 규칙에만 씀. lemma에 숫자 불가, jsonb에 저장할 수 없는 글자(짝 없는 서로게이트, NUL) 거부. pending에서만 고침 |
| test_cases | 규칙 예문 테스트 | jsonb |  |  | 관리자가 새로 쓴 예문만(사용자 원문 금지). 지금 구현은 [{text, should_apply}]. 승인하려면 '적용됨'·'적용 안 됨'이 각각 하나 이상 있고 모두 통과해야 함 |
| status | 규칙 상태 | varchar(30) |  |  | pending / approved / retired. 관리자가 admin에서만 만들고(pending), 액션으로 승인·폐기. approved만 판정에 쓰고, 패턴·용법도 approved일 때만 씀(연결된 회화체면 지금 구현은 원형도, 확인 필요). pending에서 바로 폐기할 수도 있음. 폐기는 되돌리지 않고 행은 지우지 않음(span_match.rule_id가 가리킴). 바꾸려면 폐기하고 새로 만듦. 승인은 그 패턴 자체로 매칭된 구간이 있는 분석(용법 완결 패턴이면 없음), 폐기는 그 규칙으로 정해진 분석을 stale로 만들고 세대 번호를 올림. 패턴 세트 버전은 올리지 않음(design-decisions 45절) |
| created_by | 등록자 ID | bigint | Y | → users | 시스템이 만든 규칙이면 null. 지금 구현은 Django auth 사용자(AUTH_USER_MODEL)를 가리키고, 사용자가 지워지면 null(확인 필요) |
| approved_by | 승인자 ID | bigint | Y | → users | 지금 구현은 Django auth 사용자(AUTH_USER_MODEL)(확인 필요) |
| approved_at | 승인일시 | timestamptz | Y |  |  |
| created_at | 등록일시 | timestamptz |  |  |  |
| updated_at | 수정일시 | timestamptz |  |  |  |

## sentence_analysis — 문장 분석

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| sentence_hash | 문장 해시 | char(64) |  |  | 키 텍스트(정규화+숫자 자리표시자) SHA-256. UNIQUE(sentence_hash). 공용 테이블에 원문 미저장 |
| normalize_version | 정규화 버전 | smallint |  |  | 기록용. 정규화 규칙이 바뀌면 마이그레이션으로 해시 재계산 |
| pipeline_version | 파이프라인 버전 | varchar(30) |  |  | SudachiPy·사전·판별 로직 버전 |
| matcher_version | 매칭 버전 | integer |  |  | 분석 당시 패턴 세트 버전(pattern_set_version.version). 첫 분석·stale 교체·재매칭이 매칭 직전에 읽은 값을 기록하고, 값은 낮추지 않음. 기존 행은 0. 현재 값보다 낮으면 조회 시 그 요청의 원문으로 로컬 매칭을 다시 돌려 저장된 구간에 없는 새 구간만 더함(일괄 재처리 없음, stale로 만들지 않음). DB만으로 정할 수 없는 새 구간은 같은 요청 안에서 LLM 재판정(rematch_judge)으로 정함. 재판정이 실패하면 이 값도 그대로 둬 다음 조회가 다시 시도(design-decisions 41절) |
| normalized_length | 키 텍스트 길이 | integer |  |  | 코드포인트 수. 구간 범위 검증용 |
| status | 분석 상태 | varchar(30) |  |  | processing / complete / failed. '대상 문법 없음'이나 미확정 구간이 남은 분석도 분석 자체가 성공하면 complete. partial은 두지 않음(#99, design-decisions 51절 5) |
| processing_started_at | 처리 시작일시 | timestamptz | Y |  | 조건부 UPDATE로 선점. 150초가 지나면 다음 요청이 다시 선점하며, 미완료 작업을 주기적으로 재투입하지 않음(#99, design-decisions 51절 5) |
| generation | 세대 번호 | integer |  |  | 선점할 때마다 증가. 영향 범위의 패턴·용법이 반려·반려 취소·승인 취소되거나 용법 완결이 바뀌거나 회화체가 원형에 연결·해제되거나 판별 규칙이 승인·폐기될 때도 증가. 결과 쓰기 시 비교해 늦게 끝난 이전 작업의 덮어쓰기 방지(지금 구현은 작업이 시작할 때 읽은 값과 저장할 때 잠근 행의 값이 다르면 저장을 되돌리고 행을 failed로 두며 실패 소식을 보냄. stale이면 stale 유지. 한 사건에서 여러 번 오를 수 있어 같은지만 비교, design-decisions 51절). 기본값 0 |
| is_stale | stale 여부 | boolean |  |  | 판 번호로 잡히지 않는 사건용만. 옛 결과는 '재분석 중'과 함께 표시. 판 번호가 생기기 전까지(지금 구현, #38) 반려·반려 취소·승인 취소·용법 완결 변경과 판별 규칙 승인·폐기도 이 칸으로만 기록하고, stale 분석은 다음 요청에서 다시 분석해 통째로 바꾼 뒤 false로 |
| translation_ko | 한국어 번역 | text | Y |  | 자리표시자(⟨N1⟩) 포함 형태. 자리표시자가 모두 보존된 경우에만 저장 |
| processing_translation_ko | 처리 중 번역 | text | Y |  | 처리 중 작업이 검증한 번역을 먼저 저장하는 곳(자리표시자 포함 형태). stale 재분석 중에도 translation_ko(옛 결과)를 덮지 않음. 작업이 끝나면 비움(design-decisions 51절) |
| name_spans | 이름 구간 | jsonb | Y |  | [{start, end, type: person/place/org/work/other}]. 키 텍스트 코드포인트 기준 [start, end)(word_spans와 같음)와 종류만 둔다. 새 문장 첫 LLM 요청이 토큰 ID 묶음으로 판단하고 서버가 위치를 계산한다. 형태소·문법 후보는 보존하고 주석만. NULL은 판단하지 않은 분석(이 칸이 생기기 전에 저장된 행, 또는 LLM 답이 목록이 아니었던 행)이고 이름 구간만 얻으려고 다시 분석하지 않는다. []는 이름이 없다는 판단(design-decisions 58절) |
| word_spans | 단어 구간 | jsonb | Y |  | [{start, end, sense_id}]. 키 텍스트 코드포인트 기준 [start, end)와 고른 뜻(word_sense) ID만 둔다(공용 테이블에 원문 미저장). 같은 단어가 두 번 나오면 위치마다 하나씩. 사전에서 못 찾았거나 뜻을 정하지 못한 단어는 넣지 않는다. NULL은 이 칸이 생기기 전에 저장된 행이라 다시 분석(design-decisions 50절) |
| sense_ids | 단어 뜻 ID 목록 | bigint[] | Y |  | 문장에 나온 단어 뜻(word_sense) ID 목록. word_spans의 sense_id를 중복 없이 모은 값이고 word_spans와 함께 씀. 단어는 sense에서 유도. 내 일본어 계산용. 단어·뜻 병합·삭제 시 갱신 필요(word_spans도) |
| created_at | 생성일시 | timestamptz |  |  |  |
| updated_at | 수정일시 | timestamptz |  |  |  |

## span_match — 구간 매칭

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| analysis_id | 문장 분석 ID | bigint |  | → sentence_analysis | UNIQUE(analysis_id, pattern_id, start_offset, end_offset) WHERE pattern_id IS NOT NULL: 같은 자리의 같은 패턴 구간은 하나(중복 카드 방지 백스톱). 구간을 쓰는 모든 경로는 분석 행을 잠근 뒤 씀(재매칭은 저장 열쇠가 없는지, stale 교체는 행이 아직 fresh가 아닌지 확인). 잠금 순서는 원형 연결 advisory 잠금 → 패턴과 그 패턴을 원형으로 가리키는 회화체(id 순) → 용법 → (올릴 때) 패턴 세트 버전 → 분석 행(design-decisions 41절, 42절). 회화체 연결·용법 병합은 영향 범위 분석 행을 한 번에 id 순서로 잠금(43절) |
| pattern_id | 문법 패턴 ID | bigint | Y | → grammar_pattern | 미발견 구간에서 새 패턴 등록에 실패해 패턴이 없으면 null |
| usage_id | 확정 용법 ID | bigint | Y | → grammar_usage | 연결된 회화체 구간이면 원형 용법, 그 밖에는 자기 용법. 회화체 연결 때 합친 용법을 가리키면 합칠 원형 용법으로 바꿈(candidates·alternatives도 같이, design-decisions 43절). usage_closed·usage_rule 확정은 실제 매칭된 패턴 기준 / 그 패턴 또는 variant_of 원형 소속. 조회 때 어긋나면 뺌. 저장 때는 분석할 때 읽은 원형 연결이 저장 직전과 다르면 저장하지 않음(design-decisions 42절) |
| start_offset | 시작 위치 | integer |  |  | 키 텍스트 코드포인트 기준 [start, end). 원문 위치는 서버가 변환 / 0 ≤ start < end (CHECK) |
| end_offset | 끝 위치 | integer |  |  | 0 ≤ start < end (CHECK) |
| state | 판정 상태 | varchar(30) |  |  | decided(용법이 하나로 정해짐) / not_applicable(해당 없음, 새 문법 찾지 않음) / divergent(해석 갈림) / unfound(미발견, 새 문법 등록) / unresolved(미확정·지원 범위 밖). 확정·미검수 표시는 저장하지 않고 조회 시 정함: usage_id의 grammar_usage.status, 그 용법이 속한 패턴(grammar_usage.pattern_id, 회화체 구간이면 원형)의 status, pattern_id(실제 매칭된 패턴)의 status, pattern_id가 연결된 원형(variant_of)의 status가 모두 approved면 확정, 하나라도 pending이면 미검수, 하나라도 rejected면 응답에서 뺌. alternatives의 각 usage_id도 주 용법과 같은 네 가지(그 용법, 그 용법의 소속 패턴, pattern_id, pattern_id가 연결된 원형)와 소속(pattern_id나 그 원형)으로 따로 검사(pending이면 그 대안에 배지, rejected면 그 대안만 뺌). 주 용법 쪽이 rejected면 구간째 뺌(대안을 주 용법으로 올리지 않음). unresolved는 pattern_id와 그 원형(연결됐으면)의 status만 봄(이름은 매칭된 패턴 이름, 설명 없음) / 상태별 칸(CHECK): decided면 usage_id 필수, divergent면 usage_id 필수이고 alternatives가 비어 있지 않음, unresolved면 usage_id·alternatives 모두 NULL(candidates·pattern_id는 남김), 그 밖에는 alternatives NULL |
| decided_by | 판정 근거 | varchar(30) | Y |  | single_usage / rule / llm / admin. single_usage(승인된 용법 완결 패턴의 단일 후보, #39), rule(승인된 판별 규칙, #55), llm, admin(활성 관리자 정정을 적용함, #221)을 모두 쓴다 |
| rule_id | 판별 규칙 ID | bigint | Y | → usage_rule | decided_by가 rule일 때만 있음(CHECK `span_match_rule_iff_decided_by_rule`, decided_by가 NULL이면 rule_id도 NULL). 같은 용법을 가리키는 규칙이 여럿 맞으면 지금 구현은 id가 가장 작은 규칙을 기록(확인 필요) |
| basis_revision | 근거 판 번호 | integer | Y |  | single_usage면 grammar_pattern.revision. 판 번호를 두기 전까지(지금 구현, #39) 칼럼을 만들지 않고, 다시 판정은 is_stale(design-decisions 35절)에 맡김. 판별 규칙은 승인 뒤 내용을 바꾸지 않아 판 번호가 없음(45절) |
| usage_revision | 용법 판 번호 | integer | Y |  | 판정 당시 grammar_usage.revision. 바뀌면 재검토 |
| candidates | 후보 용법 목록 | jsonb | Y |  | 서버가 부여한 후보 ID [{candidate_id, usage_id}]. 해석 갈림의 대안은 alternatives. 회화체 연결 때 합친 용법의 usage_id는 합칠 원형 용법으로 바꾸고, 그래서 겹친 후보는 앞의 것만 남김 |
| alternatives | 대안 해석 | jsonb | Y |  | 해석 갈림일 때만 [{usage_id, translation_ko}](서버가 매긴 후보 순서). translation_ko는 그 해석으로 옮긴 문장 전체 번역이고 주 번역처럼 키 텍스트 기준(자리표시자 형태). 대안의 근거는 문장을 풀어 쓴 글이라 저장하지 않음. 주 용법은 usage_id(번역과 같은 해석). 회화체 연결 때 합친 용법은 합칠 원형 용법으로 바꾸고, 주 용법과 같아졌거나 앞 대안과 겹친 대안은 뺌. 대안이 남지 않으면 state를 decided로 |
| confidence | 신뢰도 | decimal(4,3) | Y |  | LLM 자기 보고값. 정확도로 취급하지 않음 / 0~1 (CHECK) |

## match_correction — 매칭 정정

관리자가 평가 결과(eval_result) admin의 항목에서만 만든다. 공용 분석에는 원문이 없어 다른 곳에서는 문장을 고를 수 없기 때문이다(#221, design-decisions 70절). 정정은 자리(위치)로 찾고, 같은 자리의 다른 패턴 구간과는 정정 전·후 용법의 소속 패턴(회화체면 원형)으로 가른다.

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| analysis_id | 문장 분석 ID | bigint |  | → sentence_analysis | UNIQUE(analysis_id, start_offset, end_offset). 재분석해도 덮어쓰지 않음 |
| start_offset | 시작 위치 | integer |  |  | 키 텍스트 코드포인트 기준 |
| end_offset | 끝 위치 | integer |  |  |  |
| before_usage_id | 정정 전 용법 ID | bigint | Y | → grammar_usage | 처음 정정할 때의 판정 용법(다시 정정해도 바꾸지 않음). 미확정 구간이었으면 null. 미발견 구간(구간 새로 만들기)의 정정은 하지 않는다(#221) |
| after_usage_id | 정정 후 용법 ID | bigint | Y | → grammar_usage | null이면 매칭 해제 |
| status | 적용 상태 | varchar(30) |  |  | active / suspended. active만 우선 적용, 오답으로 확인된 결과는 재분석 중에도 노출 안 함(저장 구간을 보일 때 정정 구간은 정정 후 용법으로, 해제 구간은 빼고 보인다, #222). 관리자가 정정 목록(admin)의 '멈춤'·'다시 적용' 액션으로 직접 바꿀 때만 변경하고, 바꾸면 분석을 stale로 만들고 세대 번호를 올린다. 목록은 분석 ID·위치·전후 용법·상태·정정자·시각만 보이고 문장은 보이지 않는다(#223). after_usage_id 용법, 그 소속 패턴, 같은 위치 span_match의 실제 매칭 패턴(pattern_id, 회화체면 회화체 패턴), 그 패턴이 연결된 원형 중 하나라도 rejected면 적용할 때 건너뜀(상태는 그대로, 조회 규칙과 같은 네 가지) |
| corrected_by | 정정자 ID | bigint | Y | → users | 정정한 관리자가 탈퇴하면 NULL(SET_NULL). 다른 관리자 칸과 같고, 관리자 탈퇴가 막히지 않게 한다(#221) |
| created_at | 정정일시 | timestamptz |  |  |  |
| updated_at | 수정일시 | timestamptz |  |  |  |

## kanji — 한자

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| character | 한자 | varchar(4) |  |  | 한자 한 글자(코드포인트 1개). UNIQUE. 단어의 한자는 표기를 글자 단위로 잘라 이 칸으로 조회(연결 테이블 없음). 내 일본어의 한자는 아직 정하지 않았다(원문을 저장하지 않아 예전처럼 user_sentence 원문에서 뽑을 수 없다, ADR 0006) |
| on_readings | 음독 | jsonb | Y |  | KANJIDIC2 음독 목록(가타카나) |
| kun_readings | 훈독 | jsonb | Y |  | KANJIDIC2 훈독 목록(히라가나, 오쿠리가나 구분점 포함) |
| korean_readings | 한국 한자음 | jsonb | Y |  | KANJIDIC2 한국어 음(한글). 예: 学→학 |
| meaning_en | 영어 뜻 | jsonb | Y |  | KANJIDIC2 영어 뜻(CC BY-SA 4.0, 출처 표기). 한국어 뜻 생성 근거 |
| meaning_ko | 한국어 뜻 | varchar(255) | Y |  | 훈음 형태 권장(예: 배울 학). LLM 생성 후 검수 |
| meaning_source | 뜻 출처 | varchar(30) | Y |  | dictionary / llm / admin |
| meaning_status | 뜻 검수 상태 | varchar(20) |  |  | ai(검수 전, 'AI 번역' 표시) / reviewed |
| grade | 상용한자 여부·학년 | smallint | Y |  | KANJIDIC2 grade. 1~6 교육한자, 8 상용, 9·10 인명용, null=그 외 |
| stroke_count | 획수 | smallint | Y |  |  |
| updated_at | 수정 시각 | timestamptz |  |  |  |

## word_sense — 단어 뜻

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK | 고정 sense 식별자. 학습 카드(Phase 2)는 이 ID를 참조 |
| word_id | 단어 ID | bigint |  | → word | UNIQUE(word_id, jmdict_sense_index) |
| jmdict_sense_index | JMdict 뜻 번호 | smallint | Y |  | JMdict 항목 안의 sense 순번(참고용, 식별자로 쓰지 않음). LLM 뜻(sense_origin=llm, 사전에 없는 단어의 뜻과 JMdict 단어 아래 더한 뜻 모두)이면 null(#134) |
| gloss_en | 영어 뜻 | jsonb | Y |  | JMdict 영어 뜻(CC BY-SA 4.0, 출처 표기). 한국어 뜻 생성 근거. LLM 뜻(sense_origin=llm)은 NULL이고 한국어 뜻을 함께 만든다(#134 구현이 정함, 확인 필요) |
| tags | 뜻 태그 | text[] |  |  | sense 단위 태그(transitive/intransitive, honorific/humble/polite, uk, onomatopoeia, loanword, 문체 태그 colloquial·formal·archaic 등(design-decisions 67절)). JMdict pos/misc 변환, loanword는 lsource가 있는 뜻(구현이 정함, 확인 필요) |
| pair_form | 자타 대응 동사 | varchar(255) | Y |  | 이 뜻의 자타 대응 동사 표기. 화면 "타동사: 開ける"/"자동사: 開く"(라벨은 이 뜻의 자/타 태그). NULL = 짝 없음 또는 미확인. 웹페이지 단어 화면만 |
| applies_to | 적용 제한 | jsonb | Y |  | `{"forms": stagk, "readings": stagr}` 중 있는 것만(구현이 정함, 확인 필요): 이 뜻이 적용되는 표기·읽기. 뜻 후보 거르기용. 대부분 NULL |
| sense_origin | 뜻 출처 | varchar(10) |  |  | jmdict / llm. LLM 뜻은 JMdict 단어 아래에 붙어도 이 칸으로 구분 |
| sense_status | 뜻 검수 상태 | varchar(20) |  |  | 이 뜻 자체의 검수 상태. llm 출처는 pending으로 시작해 'AI 생성·미검수' 표시, jmdict는 approved. LLM 뜻은 관리자가 승인·반려하고(반려는 후보·응답에서 빠짐), 승인하면 배지가 없다(#134, design-decisions 50절 10) |
| meaning_ko | 한국어 뜻 | text | Y |  | LLM 생성 후 관리자 검수. JMdict 뜻의 한국어 뜻은 JMdict 기반이라 CC BY-SA 4.0·출처·변경 사실 표시. LLM 뜻(sense_origin=llm)은 사전 근거가 없어 출처 표시를 하지 않는다(#134) |
| meaning_source | 뜻 출처 | varchar(30) | Y |  | dictionary / llm / admin — 한국어 뜻의 출처·검수 상태(sense_origin과 별개) |
| meaning_status | 뜻 검수 상태 | varchar(20) |  |  | ai(검수 전, 'AI 번역' 표시. 한국어 뜻이 아직 없는 뜻도 ai) / reviewed(관리자가 고쳤거나 '검수 완료') / failed(`word_gloss` 생성 실패, meaning_ko는 NULL이고 다른 새 문장에 나오면 다시 만든다, #97·마이그레이션 0016) — 한국어 뜻의 출처·검수 상태(sense_origin과 별개) |
| created_at | 생성 시각 | timestamptz |  |  |  |
| updated_at | 수정 시각 | timestamptz |  |  |  |

## eval_sentence — 평가 문장

품질 평가(FR-A26, #177)의 고정 평가 세트. 관리자가 직접 쓴 문장, 이용 가능한 자료, 동의를 받은 자료만 넣는다(NFR-13). 사용자 원문이 아니라 Django admin에서 쓰고 고친다. 사용자 원문(`user_sentence`)을 옮겨 오는 기능은 없다.

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| text | 문장 | text |  |  | 평가할 문장 |
| category | 유형 | varchar(30) |  |  | normal(정상) / no_grammar(문법 없음) / homograph(동형이의) / contraction(축약) / quotation(인용) / technical(기술 문서) / out_of_scope(범위 밖). NFR-09의 유형 |
| is_active | 사용 | boolean |  |  | 기본 true. 끄면 다음 실행부터 빠진다. 지난 결과가 가리키므로 지우지 않고 끈다(admin 삭제 없음) |
| note | 메모 | text |  |  | 빈 값 허용 |
| created_at | 생성일시 | timestamptz |  |  |  |
| updated_at | 수정일시 | timestamptz |  |  |  |

## eval_run — 평가 실행

평가 세트를 한 번 돌린 것. 관리 명령 `evaluate --yes`로만 만들고(admin 추가 없음), 지표는 결과·항목에서 계산한다(design-decisions 57절).

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| status | 상태 | varchar(30) |  |  | running / complete / failed(버그 등 예외로 멈춤) |
| model | 모델 | varchar(255) |  |  | 실행 때의 `OPENAI_MODEL` |
| note | 메모 | text |  |  | 무엇을 바꿨는지. admin에서 이 칸만 고친다 |
| created_at | 실행 시각 | timestamptz |  |  |  |
| finished_at | 끝난 시각 | timestamptz | Y |  |  |

## eval_result — 평가 결과

평가 실행에서 문장 하나의 결과.

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| run_id | 평가 실행 ID | bigint |  | → eval_run | 실행을 지우면 함께 지움(CASCADE) |
| sentence_id | 평가 문장 ID | bigint |  | → eval_sentence | PROTECT |
| text | 문장 | text |  |  | 실행 때의 평가 문장. 문장을 고치면 지난 채점을 이어받지 않는 기준 |
| translation_ko | 번역 | text | Y |  | 실패면 NULL |
| failed | 실패 | boolean |  |  | 분석 실패(BusinessError)나 다른 요청이 처리 중이라 선점하지 못함 |
| error | 오류 | varchar(100) |  |  | 오류 코드나 사유. 빈 값 허용 |
| missed | 놓친 문법 수 | integer | Y |  | 관리자가 적는다. NULL은 아직 적지 않음. 지난 결과와 항목까지 같으면 그 값을 이어받는다. 구간 정확도 분모에 들어간다 |
| calls | 호출 수 | integer |  |  | 이 문장 분석의 LLM 호출 수 |
| input_tokens | 입력 토큰 | integer |  |  | 캐시된 입력 포함 |
| cached_input_tokens | 캐시된 입력 토큰 | integer |  |  |  |
| output_tokens | 출력 토큰 | integer |  |  |  |
| usage_request_id | 사용 기록 ID | bigint | Y | → usage_log | 이 문장을 분석한 request 행(user NULL). LLM 호출 행은 그 뒤의 같은 분석 행 기록이다. SET_NULL |

## eval_item — 평가 항목

평가 결과의 문법 항목 하나. 사이드 패널에 보이는 항목(구성 문법 포함, 숨긴 구성 문법 제외)이다.

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| result_id | 평가 결과 ID | bigint |  | → eval_result | CASCADE |
| start | 시작 | integer |  |  | 평가 문장의 UTF-16 위치 |
| end | 끝 | integer |  |  |  |
| surface | 구간 | varchar(255) |  |  | 그 위치의 글자 |
| state | 상태 | varchar(30) |  |  | decided / divergent / unresolved |
| name | 이름 | varchar(255) |  |  | 화면 제목: 미확정이면 패턴 이름, 그 밖에는 용법 이름 |
| pattern_name | 패턴 | varchar(255) |  |  | 실제로 매칭된 패턴 이름 |
| pattern_ref | 패턴 ID | bigint |  |  | 참조가 아닌 값. 채점 이어받기 기준 |
| usage_ref | 용법 ID | bigint | Y |  | 참조가 아닌 값(용법이 합쳐져 지워져도 남는다). 미확정이면 NULL |
| alternatives | 대안 | jsonb |  |  | 해석 갈림의 대안 용법 이름 목록 |
| review_status | 검수 상태 | varchar(30) |  |  | 실행 때 화면에 보인 검수 상태(pending / approved) |
| grade | 채점 | varchar(30) |  |  | ungraded(미채점) / correct(맞다) / ambiguous(애매하다) / wrong_usage(용법이 틀렸다) / wrong_span(구간이 틀렸다). admin에서 이 칸만 고친다. 같은 평가 문장(고치지 않은 같은 글)의 지난 실행에 위치·상태·패턴·용법·대안이 모두 같은 항목이 있으면 가장 최근 채점을 이어받는다 |

## 인덱스

- [인덱스] (PostgreSQL은 FK 인덱스 자동 생성 안 함) word.forms GIN, word.readings GIN, word.tags GIN user_sentence(analysis_id) span_match(analysis_id), span_match(pattern_id), span_match(usage_id) grammar_pattern(variant_of) word_sense(word_id) sentence_analysis.sense_ids GIN usage_log(user_id, created_at)(하루 사용량 합계, #28·마이그레이션 0018)
