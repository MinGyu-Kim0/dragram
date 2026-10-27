# Dragram

웹에서 일본어 문장을 드래그하면 번역과 함께 문법·단어·한자를 분석해 크롬 사이드 패널에 보여주는 확장 프로그램이다.
교재가 아니라 내가 직접 고른 글(기술 문서, 뉴스, 소설 등)에서 나에게 필요한 일본어를 배우는 것이 목표다.

> 새 설계로 다시 만드는 중이다. 이전 MVP는 [dragram-mvp](https://github.com/MinGyu-Kim0/dragram-mvp)(보관됨)에 있다.

## 구조

```text
backend/     Django + DRF + PostgreSQL (SudachiPy, OpenAI)
web/         React + Vite + TypeScript 웹페이지
extension/   크롬 확장 (사이드 패널)
infra/       운영 compose, nginx, Terraform
docs/        요구사항, DB 스키마, 설계 결정, ADR
compose.yaml 로컬 개발용 compose
```

`infra/`는 첫 배포 때 만든다.

## 로컬 실행

Docker(Compose 포함)가 필요하다.

```bash
cp .env.example .env   # 필요한 값만 채운다
docker compose up -d
```

- API: http://localhost:8000/api/health/
- 웹: http://localhost:5173
- 테스트: `docker compose run --rm backend pytest`, `cd web && npm test`, `cd extension && npm test`

LLM 추론 강도는 모든 호출에 `low`를 기본으로 쓴다. `.env`의 `OPENAI_REASONING_EFFORT`를 지우거나 비워도 `low`다. 변경하려면 현재 모델이 지원하는 값(예: `medium`)을 명시하고 `docker compose up -d --force-recreate backend worker`로 API 서버와 작업자를 모두 다시 만든다. `docker compose restart`만으로는 바뀐 환경변수를 읽지 않는다. SDK 허용 목록 밖의 값은 시작할 때 설정 오류로 거부하며, 추론 강도만 바꿔도 기존 분석 캐시는 그대로 재사용한다. 실제 속도·분석 품질 차이는 아직 측정하지 않았다(#217).

확장 프로그램은 compose로 띄우지 않는다. `cd extension && npm run build` 후 `chrome://extensions`에서 `extension/.output/chrome-mv3`를 압축해제된 확장 프로그램으로 불러온다.

폴더별 명령은 각 폴더의 `AGENTS.md`에 있다. PR을 올리면 CI(`.github/workflows/ci.yml`)가 바뀐 폴더의 검사(린트, 포맷, 타입, 테스트, 빌드)를 돌린다.

## 문서

- [요구사항](docs/requirements.md)
- [DB 스키마](docs/schema/schema.md)
- [설계 결정 기록](docs/design-decisions.md) · [ADR](docs/adr/)
- [디자인 기준](DESIGN.md)
- [용어집](GLOSSARY.md)
- [기여 안내](.github/CONTRIBUTING.md)

## 데이터 출처

- 단어 사전: [JMdict](https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project)
- 한자 사전: [KANJIDIC2](https://www.edrdg.org/wiki/index.php/KANJIDIC_Project)

두 데이터는 Electronic Dictionary Research and Development Group(EDRDG)의 자료이며 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)으로 제공된다. 이를 바탕으로 만든 한국어 뜻 데이터도 같은 라이선스를 따른다.

## 라이선스

코드: [MIT](LICENSE)
