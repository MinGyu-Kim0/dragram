import type { CheckingItem, GrammarItem, WordItem } from "@/utils/api";
import { AnalyzingStatus } from "./AnalysisStatus";
import { GrammarCards } from "./Grammar";
import { HiddenCards, type HiddenCard } from "./MyItems";
import { WordList, type WordListProps } from "./Words";

export type ResultTab = "grammar" | "words";

// 문법·단어 탭과 탭 내용
export function ResultTabs({
  tab,
  onTabChange,
  analyzed,
  grammar,
  checking,
  grammarCount,
  words,
  wordCount,
  hiddenGrammar,
  hiddenWords,
  wordList,
}: {
  tab: ResultTab;
  onTabChange: (tab: ResultTab) => void;
  // 분석이 끝났는가. 아니면 먼저 온 문법·단어만 보이는 중이다.
  analyzed: boolean;
  grammar: GrammarItem[];
  checking: CheckingItem[];
  grammarCount: number;
  words: WordItem[];
  wordCount: number;
  hiddenGrammar: HiddenCard[];
  hiddenWords: HiddenCard[];
  wordList: Omit<WordListProps, "words">;
}) {
  const { text, items } = wordList;
  return (
    <>
      <div role="tablist" className="tabs">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "grammar"}
          onClick={() => onTabChange("grammar")}
        >
          문법 {grammarCount}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "words"}
          onClick={() => onTabChange("words")}
        >
          단어 {wordCount}
        </button>
      </div>
      {/* 먼저 온 문법·단어만 보이는 중이다. 분석이 오면 더 채워지거나 바뀐다. 내용이 길어도
          보이게 탭 바로 밑에 둔다. */}
      {!analyzed && <AnalyzingStatus />}
      <div role="tabpanel">
        {/* 단어만 먼저 왔으면 문법 탭은 비워 둔다. 문법이 없다고 단정하지 않고 분석을 기다린다. */}
        {tab === "grammar" &&
        !analyzed &&
        grammar.length + checking.length === 0 ? null : tab === "grammar" ? (
          <>
            <GrammarCards
              text={text}
              grammar={grammar}
              checking={checking}
              items={items}
            />
            {items && <HiddenCards cards={hiddenGrammar} items={items} />}
          </>
        ) : (
          <>
            <WordList {...wordList} words={words} />
            {items && <HiddenCards cards={hiddenWords} items={items} />}
          </>
        )}
      </div>
    </>
  );
}
