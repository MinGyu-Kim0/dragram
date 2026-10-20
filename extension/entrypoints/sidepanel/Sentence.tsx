import type { Analysis, Translation } from "@/utils/api";
import type { DragRange } from "./drag-range";
import { GrammarCards, HighlightedText } from "./Grammar";
import { WordList } from "./Words";

// 문장 하나의 분석 결과. 없으면 아직 번역도 오지 않았다. translated는 번역만 와서
// 문법·단어를 기다리는 중이다. failed에 번역이 있으면 번역 뒤 문법·단어에서 실패했다.
export type SentenceResult =
  | { status: "translated"; translation: Translation }
  | { status: "done"; analysis: Analysis }
  | { status: "failed"; translation?: Translation };

// 지금 보일 번역과 루비
function translationOf(result: SentenceResult | undefined) {
  if (result?.status === "done") return result.analysis;
  return result?.translation;
}

export type ResultTab = "grammar" | "words";

// 문장 한 페이지: 원문 카드(원문, 번역) → 문법·단어 탭 → 탭 내용
export function SentenceView({
  text,
  selection,
  showHandles,
  onToggleHandles,
  showRuby,
  onToggleRuby,
  result,
  tab,
  onTabChange,
}: {
  text: string;
  selection: DragRange;
  showHandles: boolean;
  onToggleHandles: () => void;
  showRuby: boolean;
  onToggleRuby: () => void;
  result: SentenceResult | undefined;
  tab: ResultTab;
  onTabChange: (tab: ResultTab) => void;
}) {
  const translation = translationOf(result);
  return (
    <>
      <section className="sentence-card">
        <div className="display-toggles">
          <button type="button" aria-pressed={showRuby} onClick={onToggleRuby}>
            루비
          </button>
          <button
            type="button"
            aria-pressed={showHandles}
            onClick={onToggleHandles}
          >
            드래그 표시
          </button>
        </div>
        <p lang="ja" className="original">
          <HighlightedText
            text={text}
            grammar={result?.status === "done" ? result.analysis.grammar : []}
            ruby={showRuby && translation ? translation.ruby : []}
            dragHandles={showHandles ? selection : undefined}
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
        {translation && (
          <p className="translation">{translation.translation_ko}</p>
        )}
        {result?.status === "failed" && !translation && (
          <p className="error">분석하지 못했습니다</p>
        )}
      </section>
      {result?.status === "translated" && (
        <div
          role="status"
          aria-label="문법·단어를 불러오는 중"
          className="skeleton below-card"
        >
          <span />
          <span />
        </div>
      )}
      {result?.status === "failed" && translation && (
        <p className="error below-card">문법·단어를 분석하지 못했습니다</p>
      )}
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
              <GrammarCards
                text={text}
                grammar={result.analysis.grammar}
                selection={selection}
              />
            ) : (
              <WordList words={result.analysis.words} selection={selection} />
            )}
          </div>
        </>
      )}
    </>
  );
}
