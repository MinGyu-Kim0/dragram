import type { Analysis } from "@/utils/api";
import { GrammarCards, HighlightedText, type DragRange } from "./Grammar";
import { WordList } from "./Words";

// 문장 하나의 분석 결과. 없으면 아직 분석 중이다.
export type SentenceResult =
  { status: "done"; analysis: Analysis } | { status: "failed" };

export type ResultTab = "grammar" | "words";

// 문장 한 페이지: 원문 카드(원문, 번역) → 문법·단어 탭 → 탭 내용
export function SentenceView({
  text,
  selection,
  result,
  tab,
  onTabChange,
}: {
  text: string;
  selection: DragRange;
  result: SentenceResult | undefined;
  tab: ResultTab;
  onTabChange: (tab: ResultTab) => void;
}) {
  return (
    <>
      <section className="sentence-card">
        <p lang="ja" className="original">
          <HighlightedText
            text={text}
            grammar={result?.status === "done" ? result.analysis.grammar : []}
            selection={selection}
          />
        </p>
        <hr />
        {!result && (
          <div
            role="status"
            aria-label="번역을 불러오는 중"
            className="skeleton"
          >
            <span />
            <span />
          </div>
        )}
        {result?.status === "done" && (
          <p className="translation">{result.analysis.translation_ko}</p>
        )}
        {result?.status === "failed" && (
          <p className="error">분석하지 못했습니다</p>
        )}
      </section>
      {result?.status === "done" && (
        <>
          <div role="tablist" className="tabs">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "grammar"}
              onClick={() => onTabChange("grammar")}
            >
              문법 {result.analysis.grammar.length}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "words"}
              onClick={() => onTabChange("words")}
            >
              단어 {result.analysis.words.length}
            </button>
          </div>
          <div role="tabpanel">
            {tab === "grammar" ? (
              <GrammarCards text={text} grammar={result.analysis.grammar} />
            ) : (
              <WordList words={result.analysis.words} />
            )}
          </div>
        </>
      )}
    </>
  );
}
