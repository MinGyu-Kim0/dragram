import type { WordItem } from "@/utils/api";
import { draggedFirst, type DragRange } from "./drag-range";

// 단어 행: 사전형(표제), 읽기, 이 문장에서의 뜻. 드래그 범위와 겹친 단어를 먼저 두고,
// 각 묶음 안은 원문 순서로 보인다.
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
    <ul className="word-list" aria-label="단어">
      {draggedFirst(sorted, selection).map(({ item: word, dragged }) => (
        <li
          key={`${word.start}-${word.end}-${word.lemma}`}
          className={dragged ? "word-row dragged" : "word-row"}
        >
          <div className="word-head">
            <h3 lang="ja">{word.lemma}</h3>
            <span lang="ja" className="word-reading">
              {word.reading}
            </span>
            {dragged && <span className="card-meta">드래그한 부분</span>}
          </div>
          <p className="word-meaning">
            {word.meaning_ko}
            {/* JMdict 없이 LLM이 만든 뜻이라 'AI 번역'이 아닌 이 배지를 쓴다(#10). */}
            {word.review_status === "pending" && (
              <span className="badge-warn">AI 생성·미검수</span>
            )}
          </p>
        </li>
      ))}
    </ul>
  );
}
