# DB 스키마 (PostgreSQL)

원본: `erd.json`(ERDCloud 스냅샷). 이 문서는 그 파일에서 생성했다. 결정 근거는 `../design-decisions.md` 참고.

> 설계 시점 스냅샷이다. 구현을 시작하면 Django 모델과 마이그레이션이 기준이고, 이 문서는 바뀐 부분을 손으로 맞춘다.
> design-decisions 28절 변경(`grammar_pattern.status`, `span_match.state` 값)은 이 문서에만 반영했고 `erd.json`에는 아직 반영하지 않았다.

## users — 사용자

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| google_sub | 구글 계정 식별자 | varchar(255) |  |  | Google OAuth sub, UNIQUE |
| email | 이메일 | varchar(255) |  |  | UNIQUE |
| is_staff | 관리자 여부 | boolean |  |  | 패턴·용법 승인 권한(Django admin) |
| created_at | 가입일시 | timestamptz |  |  |  |

## user_sentence — 분석 기록

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| user_id | 사용자 ID | bigint |  | → users | 개인 데이터. 본인만 조회, 탈퇴 시 삭제 |
| original_hash | 원문 해시 | char(64) |  |  | 정규화 전 원문 SHA-256. UNIQUE(user_id, original_hash). 숫자만 다른 원문(1人/2人)도 따로 보관 |
| analysis_id | 공용 분석 ID | bigint |  | → sentence_analysis | sentence_analysis.id 참조(FK). 여러 사용자·숫자만 다른 원문이 같은 공용 분석을 가리킴. 해시는 조인해서 조회. 인덱스 있음(내 일본어 조회용). 정규화 규칙 변경 시 원문별로 새 키를 계산해 해당 분석이 준비되면 analysis_id를 재연결 |
| original_text | 원문 | text |  |  | 정규화 전 원문. 개인 테이블에만 저장, 카드 예문 표시용 / 개인 원문, 본인만 조회, Django admin 미노출 |
| selected_start | 드래그 시작 위치 | integer |  |  | original_text 코드포인트 기준. 실제로 드래그한 범위(문장 끝까지 자동 확장과 별도로 강조 표시) |
| selected_end | 드래그 끝 위치 | integer |  |  | 반열린 구간 [start, end) |
| created_at | 처음 분석일시 | timestamptz |  |  |  |
| last_analyzed_at | 마지막 분석일시 | timestamptz |  |  | 같은 원문을 다시 분석하면 행을 새로 만들지 않고 갱신 |

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

## usage_log — 사용 기록

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| user_id | 사용자 ID | bigint | Y | → users | 시스템 일괄 작업 호출이면 null |
| analysis_id | 문장 분석 ID | bigint | Y | → sentence_analysis |  |
| kind | 기록 종류 | varchar(30) |  |  | request(분석 요청) / llm(LLM 호출). 원문은 저장하지 않음 |
| path | 처리 경로 | varchar(30) | Y |  | request일 때: cache / db / llm |
| purpose | 호출 목적 | varchar(30) | Y |  | llm일 때: first_response(번역+판별+새 문법 찾기 1회 호출) / reask(용법 재질문·해석 갈림 근거 재질문) / example_rewrite(원문을 베낀 새 예문 다시 쓰기) / word_gloss(단어 뜻·태그) / kanji_gloss(한자 한국어 뜻) |
| model | 모델명 | varchar(255) | Y |  |  |
| input_tokens | 입력 토큰 수 | integer | Y |  |  |
| cached_input_tokens | 캐시된 입력 토큰 수 | integer | Y |  | 프롬프트 캐싱 효과 확인용(cached_tokens) |
| output_tokens | 출력 토큰 수 | integer | Y |  |  |
| success | 성공 여부 | boolean |  |  |  |
| attempt | 시도 차수 | smallint | Y |  | 재시도 횟수·일일 상한 집계용 |
| created_at | 기록일시 | timestamptz |  |  |  |

## admin_action_log — 관리자 작업 이력

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
| dictionary_form | 원형 | varchar(255) |  |  | 대표 표기(표시용). 조회는 forms. 뜻은 word_sense |
| reading | 읽기 | varchar(255) |  |  | 대표 읽기(표시용). 조회는 readings |
| forms | 모든 표기 | text[] |  |  | JMdict 항목의 모든 한자·가나 표기. GIN. SudachiPy 사전형으로 조회 |
| readings | 모든 읽기 | text[] |  |  | 모든 읽기(히라가나 통일). GIN. 비활용어·가나 표기 단어 조회용 |
| is_common | 흔한 단어 | boolean |  |  | JMdict ichi1/news1/spec1 등. 후보가 여럿일 때 순서 힌트 |
| reading_restrictions | 읽기 제한 | jsonb | Y |  | re_restr: 읽기→허용 표기 목록. 표기에 맞는 읽기 표시·후보 거르기용. 대부분 NULL |
| pos | 품사 | varchar(255) |  |  |  |
| tags | 단어 태그 | text[] |  |  | 영문 코드 배열. 단어 전체 태그(품사·동사 그룹·い/な형용사·고유명사·예외 활용) + 검색용 sense 태그 합집합. GIN. 허용 목록은 코드 상수 |
| jmdict_seq | JMdict 항목 번호 | integer | Y |  | UNIQUE. JMdict 항목 1개 = word 1행. 사전에 없는 단어(LLM 생성)면 NULL / 사전에 없는 단어 중복 방지: 부분 UNIQUE(dictionary_form, reading) WHERE jmdict_seq IS NULL (저장 전 가나 정규화, 빈 값 금지, 대표 표기 고정) |
| updated_at | 수정일시 | timestamptz |  |  |  |

## grammar_pattern — 문법 패턴

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| name | 패턴명 | varchar(255) |  |  | 예: 명사+で |
| morpheme_key | 형태소 열 키 | char(64) |  |  | 형태소 행(lemma\|pos1\|pos2\|conj, 아무거나는 *)을 순서대로 이은 문자열의 SHA-256. UNIQUE(morpheme_key). lemma 규칙: 조사·조동사는 SudachiPy dictionary_form(축약형 보존), 동사·형용사 등 내용어는 normalized_form(표기 통일). 탁음화 조건부 매핑: 앞 토큰이 1그룹 음편형(撥音便·イ音便)이면 で→て, でる→てる, じゃう→ちゃう, だ→た, だら→たら. 동시 생성은 get_or_create |
| register | 말투 | varchar(20) |  |  | standard / colloquial. 배지 표시용(colloquial이면 '회화체' 배지). 설명·용법은 variant_of 원형 것을 참조 |
| usage_closed | 용법 완결 여부 | boolean |  |  | 관리자가 용법이 하나뿐이라고 확인한 패턴. 활용형 조건 검토 필수 |
| revision | 패턴 판 번호 | integer |  |  | 용법 완결 여부·형태소 조건·용법 구성이 바뀌면 증가. span_match.basis_revision과 조회 시 비교 |
| show_parts | 구성 문법 표시 여부 | boolean |  |  | 긴 패턴 안의 구성 문법을 화면에서 펼쳐 보일지. 화면 접기 전용, 분석 후보는 항상 보존 |
| test_cases | 검증 예문 | jsonb |  |  | [{text, should_match}] 성공·실패 예문. 첫 '걸려야 함' 항목은 등록 때 LLM이 새로 쓴 예문(원문을 베꼈으면 거부: 키 텍스트가 같거나, 원문 전체를 포함하거나, 원문의 연속된 일부를 기준 길이 이상 포함). 전부 통과해야 승인·용법 완결 가능. 새로 쓴 should_match true·false 예문이 각각 1개 이상 있어야 하고 빈 배열은 통과 아님 / LLM·관리자가 새로 쓴 예문만, 사용자 원문 저장 금지(매칭기로 확인 후 저장, 회귀 테스트 겸용) |
| is_active | 활성 여부 | boolean |  |  | 활성화 근거(등록 때 원래 문장 재매칭 통과 + 새로 쓴 should_match 예문 1개 이상 통과, LLM·관리자 예문 모두 인정)가 있고 rejected가 아니면 true. 반려 취소·예문 보완 때 서버가 다시 검증. false면 매칭에 쓰지 않음 |
| status | 승인 상태 | varchar(30) |  |  | pending / approved / rejected. 형태소 조건의 검수 상태(용법 승인과 별개). LLM이 만든 패턴은 pending으로 생성. 원형에 연결된 회화체 패턴의 미검수 여부도 이 칸으로 판단 |
| created_at | 등록일시 | timestamptz |  |  |  |
| variant_of | 원형 패턴 | bigint | Y | → grammar_pattern | 회화체 패턴이 가리키는 원형 패턴(자기 참조). 1단계만·체인 금지(원형은 variant_of null). 회화체는 자기 용법 없이 원형 용법을 씀 / 체인 금지, 연결된 회화체는 자기 용법 없음 |

## pattern_morpheme — 패턴 형태소

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| pattern_id | 문법 패턴 ID | bigint |  | → grammar_pattern |  |
| seq | 순서 | smallint |  |  | UNIQUE(pattern_id, seq) |
| lemma | 표제어 | varchar(255) | Y |  | 조사·조동사는 SudachiPy dictionary_form(축약형 보존), 동사·형용사 등 내용어는 normalized_form(표기 통일). 탁음화 조건부 매핑: 앞 토큰이 1그룹 음편형(撥音便·イ音便)이면 で→て, でる→てる, じゃう→ちゃう, だ→た, だら→たら. null이면 아무거나(정확히 1토큰) |
| pos1 | 품사 대분류 | varchar(30) | Y |  | null이면 아무거나 |
| pos2 | 품사 중분류 | varchar(30) | Y |  |  |
| conjugation_form | 활용형 | varchar(30) | Y |  | 과거/조건(終止形 vs 仮定形)처럼 구분이 필요한 패턴은 필수 |

## grammar_usage — 용법

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| pattern_id | 문법 패턴 ID | bigint |  | → grammar_pattern |  |
| name | 용법명 | varchar(255) |  |  | 예: で-수단, UNIQUE(pattern_id, name) |
| explanation_ko | 한국어 설명 | text |  |  | LLM이 처음 1회 작성 → 관리자 검수. 공용 재사용 |
| example_ja | 예문 | text | Y |  | LLM·관리자가 새로 쓴 예문만, 사용자 원문 저장 금지 |
| revision | 용법 판 번호 | integer |  |  | 설명이 아닌 의미 정의가 바뀌면 증가. span_match.usage_revision과 조회 시 비교 |
| status | 승인 상태 | varchar(30) |  |  | pending / approved / rejected. pending은 'AI 생성·미검수' 배지로 표시, 확정 판별 근거로는 approved만. rejected는 판정·규칙·LLM 후보에서 빼고 응답에도 보이지 않음. 반려·반려 취소 시 그 패턴과 그 패턴을 원형으로 가리키는 회화체 패턴의 분석을 stale로 |
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
| usage_id | 용법 ID | bigint |  | → grammar_usage | 조건이 맞으면 이 용법으로 확정 |
| pattern_id | 패턴 ID | bigint |  | → grammar_pattern | 실제 매칭된 패턴의 승인 규칙만 적용(회화체가 원형 용법을 공유해도 규칙은 패턴별) |
| condition | 판별 조건 | jsonb |  |  | 앞뒤 형태소 조건. 예: 앞 명사가 지명이면 で-장소 |
| status | 규칙 상태 | varchar(30) |  |  | pending / approved / retired. approved만 판정에 사용 |
| revision | 규칙 판 번호 | integer |  |  | 조건을 바꾸면 증가. span_match.basis_revision과 비교 |
| created_by | 등록자 ID | bigint | Y | → users | 시스템이 만든 규칙이면 null |
| approved_by | 승인자 ID | bigint | Y | → users |  |
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
| matcher_version | 매칭 버전 | integer |  |  | 분석 당시 패턴 세트 버전. 현재 값보다 낮으면 조회 시 로컬 매칭만 다시 돌림(LLM 없음) |
| normalized_length | 키 텍스트 길이 | integer |  |  | 코드포인트 수. 구간 범위 검증용 |
| status | 분석 상태 | varchar(30) |  |  | processing / complete / partial / failed. '대상 문법 없음'(LLM이 확인한 결과 분석할 문법이 없음)도 complete |
| processing_started_at | 처리 시작일시 | timestamptz | Y |  | 조건부 UPDATE로 선점. 선점 만료 판단과 미완료 작업 재투입 기준 |
| generation | 세대 번호 | integer |  |  | 선점할 때마다 증가. 결과 쓰기 시 비교해 늦게 끝난 이전 작업의 덮어쓰기 방지 |
| is_stale | stale 여부 | boolean |  |  | 판 번호로 잡히지 않는 사건용만. 옛 결과는 '재분석 중'과 함께 표시 |
| translation_ko | 한국어 번역 | text | Y |  | 자리표시자(⟨N1⟩) 포함 형태. 자리표시자가 모두 보존된 경우에만 저장 |
| name_spans | 고유명사 구간 | jsonb | Y |  | [{start, end, type: person/place/org/work/other}]. 형태소·문법 후보는 보존하고 주석만 |
| sense_ids | 단어 뜻 ID 목록 | bigint[] | Y |  | 문장에 나온 단어 뜻(word_sense) ID 목록. 단어는 sense에서 유도. 내 일본어 계산용. 단어·뜻 병합·삭제 시 갱신 필요 |
| created_at | 생성일시 | timestamptz |  |  |  |
| updated_at | 수정일시 | timestamptz |  |  |  |

## span_match — 구간 매칭

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| analysis_id | 문장 분석 ID | bigint |  | → sentence_analysis |  |
| pattern_id | 문법 패턴 ID | bigint | Y | → grammar_pattern | 미발견 구간에서 새 패턴 등록에 실패해 패턴이 없으면 null |
| usage_id | 확정 용법 ID | bigint | Y | → grammar_usage | 회화체 패턴이 원형에 연결됐으면(variant_of) 원형 용법만, 미연결이면 자기 용법만 허용(서버 검증). usage_closed·usage_rule 확정은 실제 매칭된 패턴 기준 / 그 패턴 또는 variant_of 원형 소속(트랜잭션 검증) |
| start_offset | 시작 위치 | integer |  |  | 키 텍스트 코드포인트 기준 [start, end). 원문 위치는 서버가 변환 / 0 ≤ start < end (CHECK) |
| end_offset | 끝 위치 | integer |  |  | 0 ≤ start < end (CHECK) |
| state | 판정 상태 | varchar(30) |  |  | decided(용법이 하나로 정해짐) / not_applicable(해당 없음, 새 문법 찾지 않음) / divergent(해석 갈림) / unfound(미발견, 새 문법 등록) / unresolved(미확정·지원 범위 밖). 확정·미검수 표시는 저장하지 않고 조회 시 정함: usage_id의 grammar_usage.status와 pattern_id의 grammar_pattern.status가 모두 approved면 확정, 하나라도 pending이면 미검수, 하나라도 rejected면 응답에서 뺌. alternatives의 각 usage_id도 따로 검사(pending이면 그 대안에 배지, rejected면 그 대안만 뺌) / 상태별 필수 FK(decided·divergent면 usage_id 필수) |
| decided_by | 판정 근거 | varchar(30) | Y |  | single_usage / rule / llm / admin |
| rule_id | 판별 규칙 ID | bigint | Y | → usage_rule | decided_by가 rule일 때만 |
| basis_revision | 근거 판 번호 | integer | Y |  | single_usage면 grammar_pattern.revision, rule이면 usage_rule.revision |
| usage_revision | 용법 판 번호 | integer | Y |  | 판정 당시 grammar_usage.revision. 바뀌면 재검토 |
| candidates | 후보 용법 목록 | jsonb | Y |  | 서버가 부여한 후보 ID [{candidate_id, usage_id}]. 해석 갈림의 대안은 alternatives |
| alternatives | 대안 해석 | jsonb | Y |  | 해석 갈림일 때만 [{usage_id, translation_ko}]. 주 용법은 usage_id(번역과 같은 해석) |
| confidence | 신뢰도 | decimal(4,3) | Y |  | LLM 자기 보고값. 정확도로 취급하지 않음 / 0~1 (CHECK) |

## match_correction — 매칭 정정

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| analysis_id | 문장 분석 ID | bigint |  | → sentence_analysis | UNIQUE(analysis_id, start_offset, end_offset). 재분석해도 덮어쓰지 않음 |
| start_offset | 시작 위치 | integer |  |  | 키 텍스트 코드포인트 기준 |
| end_offset | 끝 위치 | integer |  |  |  |
| before_usage_id | 정정 전 용법 ID | bigint | Y | → grammar_usage | 미발견 구간이었으면 null |
| after_usage_id | 정정 후 용법 ID | bigint | Y | → grammar_usage | null이면 매칭 해제 |
| status | 적용 상태 | varchar(30) |  |  | active / suspended. active만 우선 적용, 오답으로 확인된 결과는 재분석 중에도 노출 안 함. 관리자가 직접 바꿀 때만 변경. after_usage_id 용법이나 그 패턴이 rejected면 적용할 때 건너뜀(상태는 그대로) |
| corrected_by | 정정자 ID | bigint |  | → users |  |
| created_at | 정정일시 | timestamptz |  |  |  |
| updated_at | 수정일시 | timestamptz |  |  |  |

## kanji — 한자

| 칼럼 | 이름 | 타입 | NULL | 참조 | 설명 |
|---|---|---|---|---|---|
| id | ID | bigint |  | PK |  |
| character | 한자 | varchar(4) |  |  | 한자 한 글자(코드포인트 1개). UNIQUE. 단어의 한자는 표기를 글자 단위로 잘라 이 칸으로 조회(연결 테이블 없음). 만난 한자는 사전형이 아니라 user_sentence 원문에서 추출 |
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
| jmdict_sense_index | JMdict 뜻 번호 | smallint | Y |  | JMdict 항목 안의 sense 순번(참고용, 식별자로 쓰지 않음). 사전에 없는 전문 용어면 null(내부 sense 1개) |
| gloss_en | 영어 뜻 | jsonb | Y |  | JMdict 영어 뜻(CC BY-SA 4.0, 출처 표기). 한국어 뜻 생성 근거 |
| tags | 뜻 태그 | text[] |  |  | sense 단위 태그(transitive/intransitive, honorific/humble/polite, uk 등). JMdict pos/misc 변환 |
| pair_form | 자타 대응 동사 | varchar(255) | Y |  | 이 뜻의 자타 대응 동사 표기. 화면 "타동사: 開ける"/"자동사: 開く"(라벨은 이 뜻의 자/타 태그). NULL = 짝 없음 또는 미확인. 웹페이지 단어 화면만 |
| applies_to | 적용 제한 | jsonb | Y |  | stagk/stagr: 이 뜻이 적용되는 표기·읽기. 뜻 후보 거르기용. 대부분 NULL |
| sense_origin | 뜻 출처 | varchar(10) |  |  | jmdict / llm. LLM 뜻은 JMdict 단어 아래에 붙어도 이 칸으로 구분 |
| sense_status | 뜻 검수 상태 | varchar(20) |  |  | 이 뜻 자체의 검수 상태. llm 출처는 pending으로 시작해 'AI 생성·미검수' 표시, jmdict는 approved |
| meaning_ko | 한국어 뜻 | text | Y |  | LLM 생성 후 관리자 검수. JMdict 기반이라 CC BY-SA 4.0·출처·변경 사실 표시 |
| meaning_source | 뜻 출처 | varchar(30) | Y |  | dictionary / llm / admin — 한국어 뜻의 출처·검수 상태(sense_origin과 별개) |
| meaning_status | 뜻 검수 상태 | varchar(20) |  |  | ai(검수 전, 'AI 번역' 표시) / reviewed — 한국어 뜻의 출처·검수 상태(sense_origin과 별개) |
| created_at | 생성 시각 | timestamptz |  |  |  |
| updated_at | 수정 시각 | timestamptz |  |  |  |

## 인덱스

- [인덱스] (PostgreSQL은 FK 인덱스 자동 생성 안 함) word.forms GIN, word.readings GIN, word.tags GIN user_sentence(analysis_id) span_match(analysis_id), span_match(pattern_id), span_match(usage_id) grammar_pattern(variant_of) word_sense(word_id) sentence_analysis.sense_ids GIN
