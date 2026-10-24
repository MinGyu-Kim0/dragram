import type { WordItem, WordSense } from "@/utils/api";
import { draggedFirst, type DragRange } from "./drag-range";

// 태그 코드의 화면 이름(DESIGN.md 5장). 모르는 코드는 보이지 않는다.
const TAG_NAMES: Record<string, string> = {
  noun: "명사",
  proper_noun: "고유명사",
  pronoun: "대명사",
  verb: "동사",
  group1: "1그룹",
  group1_exception: "예외 1그룹",
  group2: "2그룹",
  group3: "3그룹",
  i_adjective: "い형용사",
  na_adjective: "な형용사",
  adverb: "부사",
  adnominal: "연체사",
  conjunction: "접속사",
  interjection: "감탄사",
  transitive: "타동사",
  intransitive: "자동사",
  honorific: "존경어",
  humble: "겸양어",
  polite: "정중어",
  uk: "보통 가나로 씀",
  onomatopoeia: "의성어·의태어",
  loanword: "외래어",
};

// 동사 그룹이 품사 바로 뒤에 오도록 화면 순서를 정한다.
const TAG_ORDER = Object.keys(TAG_NAMES);

// 단어 전체 태그와 고른 뜻의 태그 가운데 화면 이름이 있는 것(TAG_NAMES 순서)
function tagNames(word: WordItem) {
  const codes = new Set([...word.tags, ...(word.sense?.tags ?? [])]);
  return TAG_ORDER.filter((code) => codes.has(code)).map(
    (code) => TAG_NAMES[code]!,
  );
}

// 뜻 한 줄: 한국어 뜻을 보이고, 배지는 서버가 준 출처·검수 상태로 정한다. LLM이 만든 뜻이나 검수
// 전 뜻은 'AI 생성·미검수', 사전 뜻을 옮긴 검수 전 한국어 뜻은 'AI 번역'이다. 영어 뜻은 보이지
// 않는다. 한국어 뜻이 아직 없으면 준비 중, 만들지 못했으면 실패 문구다(#97).
function Meaning({ sense }: { sense: WordSense }) {
  if (sense.meaning_ko === null) {
    return sense.meaning_status === "failed" ? (
      <p className="word-meaning word-choosing">뜻을 만들지 못했습니다</p>
    ) : (
      <Preparing />
    );
  }
  const pending = sense.origin === "llm" || sense.status === "pending";
  const translated = !pending && sense.meaning_status === "ai";
  return (
    <p className="word-meaning">
      {sense.meaning_ko}
      {pending && <span className="badge-warn">AI 생성·미검수</span>}
      {translated && <span className="badge-warn">AI 번역</span>}
    </p>
  );
}

function Preparing() {
  return (
    <p
      role="status"
      aria-label="뜻을 준비하는 중"
      className="word-meaning word-choosing"
    >
      뜻을 준비하는 중
    </p>
  );
}

// 단어 행: 사전형(표제), 읽기, 태그, 이 문장에서 고른 뜻. 드래그 범위와 겹친 단어를 먼저 두고,
// 각 묶음 안은 원문 순서로 보인다. 뜻을 아직 고르지 않았거나 한국어 뜻이 아직 없는 단어는 뜻 자리에 대기 표시를 둔다.
// 목록 아래에 JMdict 출처 각주를 단다.
export function WordList({
  words,
  selection,
}: {
  words: WordItem[];
  selection: DragRange;
}) {
  if (words.length === 0) {
    return <p className="no-words">단어 없음</p>;
  }
  const sorted = [...words].sort((a, b) => a.start - b.start || a.end - b.end);
  return (
    <>
      <ul className="word-list" aria-label="단어">
        {draggedFirst(sorted, selection).map(({ item: word, dragged }) => {
          const tags = tagNames(word);
          return (
            <li
              key={`${word.start}-${word.end}`}
              className={dragged ? "word-row dragged" : "word-row"}
            >
              <div className="word-head">
                <h3 lang="ja">{word.dictionary_form}</h3>
                <span lang="ja" className="word-reading">
                  {word.reading}
                </span>
                {dragged && <span className="card-meta">드래그한 부분</span>}
              </div>
              {tags.length > 0 && (
                <ul className="word-tags" aria-label="태그">
                  {tags.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              )}
              {word.sense ? <Meaning sense={word.sense} /> : <Preparing />}
            </li>
          );
        })}
      </ul>
      <p className="source-note">
        단어 정보:{" "}
        <a
          href="https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project"
          target="_blank"
          rel="noreferrer"
        >
          JMdict
        </a>{" "}
        (EDRDG,{" "}
        <a
          href="https://creativecommons.org/licenses/by-sa/4.0/"
          target="_blank"
          rel="noreferrer"
        >
          CC BY-SA 4.0
        </a>
        ). 이 문장에 맞는 뜻만 골라 보여 줘요.
      </p>
    </>
  );
}
