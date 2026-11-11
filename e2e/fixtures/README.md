# E2E 고정 데이터

- `sentences.ts`: 시나리오가 쓰는 고정 문장. 관리자가 새로 쓴 문장만 둔다.
- `seed.json`: 스택을 띄울 때 `loaddata`로 넣는 행. 고정 문장에 필요한 것만 둔다.
  - 문법: 패턴 `ている`(승인·용법 완결 → LLM 없이 확정), `ので`(미검수, 용법 하나 → 확인 중), `명사+で`(미검수, 용법 둘 → 확인 중)와 그 형태소·용법. 로컬 개발 DB에서 LLM이 등록한 행을 `dumpdata`로 뽑고 `ている`만 승인 상태로 바꿨다.
  - 단어: 雨·降る·今日·家·本·読む의 JMdict 행(word·word_sense). 한국어 뜻(`meaning_ko`)은 비워 두어 처음 적재한 상태와 같게 했다.

고정 문장을 바꾸면 그 문장의 문법·단어가 여기 있는지 다시 확인한다.

단어 데이터는 [JMdict](https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project)(EDRDG, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/))에서 왔다.
