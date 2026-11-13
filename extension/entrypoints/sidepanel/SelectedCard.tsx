import type { GrammarItem, WordItem } from "@/utils/api";
import { GrammarCard } from "./Grammar";
import { WordList, type WordListProps } from "./Words";

// 원문을 눌러 고른 글자의 '선택한 카드'(#354): 그 글자의 문법 카드와 그 아래 단어 카드
export function SelectedCard({
  grammar,
  words,
  wordList,
  onClose,
}: {
  grammar: GrammarItem | undefined;
  words: WordItem[];
  wordList: Omit<WordListProps, "words">;
  onClose: () => void;
}) {
  return (
    <section aria-label="선택한 카드" className="selected-card">
      <div className="selected-card-head">
        <span className="card-meta">선택한 카드</span>
        <button type="button" className="text-button" onClick={onClose}>
          닫기
        </button>
      </div>
      {/* 목록과 같은 카드라 추가·숨김 버튼도 같다. */}
      {grammar && (
        <ul className="grammar-cards">
          <GrammarCard
            text={wordList.text}
            item={grammar}
            items={wordList.items}
          />
        </ul>
      )}
      {words.length > 0 && <WordList {...wordList} words={words} />}
    </section>
  );
}
