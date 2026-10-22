import type {
  Analysis,
  CheckingItem,
  GrammarItem,
  Translation,
} from "@/utils/api";
import type { DragRange } from "./drag-range";
import { GrammarCards, HighlightedText } from "./Grammar";
import { WordList } from "./Words";

// 문장 하나의 분석 결과. 없으면 아직 아무것도 오지 않았다. early는 번역보다 먼저 온
// grammar 이벤트(LLM 없이 확정한 문법 earlyGrammar, 판별 대상 구간 checking)만 와서
// 번역을 기다리는 중이다. translated는 번역이 와서 문법·단어를 기다리는 중이다. failed에 번역이
// 있으면 번역 뒤 문법·단어에서 실패했다. earlyGrammar는 analysis가 오기 전까지 보이고,
// checking은 실패하면 지운다. reanalyzing은 stale 분석의 옛 결과(previous)를 보이며 새 결과를
// 기다리는 중(재분석 중)이고, 그러다 실패하면 failed에 옛 결과만 남는다.
export type SentenceResult =
  | { status: "early"; earlyGrammar: GrammarItem[]; checking: CheckingItem[] }
  | {
      status: "translated";
      translation: Translation;
      earlyGrammar?: GrammarItem[];
      checking?: CheckingItem[];
    }
  | { status: "done"; analysis: Analysis }
  | { status: "reanalyzing"; previous: Analysis }
  | {
      status: "failed";
      translation?: Translation;
      earlyGrammar?: GrammarItem[];
      previous?: Analysis;
    };

// 지금 보일 완성된 분석. 분석이 끝났으면 그 결과, 다시 분석하는 중이거나 그러다 실패했으면 옛 결과다.
function analysisOf(result: SentenceResult | undefined) {
  if (result?.status === "done") return result.analysis;
  if (result?.status === "reanalyzing" || result?.status === "failed") {
    return result.previous;
  }
  return undefined;
}

// 지금 보일 판별 대상 구간(확인 중). 분석이 끝나거나 실패하면 없다.
function checkingOf(result: SentenceResult | undefined) {
  if (result?.status === "early" || result?.status === "translated") {
    return result.checking ?? [];
  }
  return [];
}

// 지금 보일 문법. 분석이 끝나기 전에는 먼저 온 문법만 보인다.
function grammarOf(result: SentenceResult | undefined) {
  const analysis = analysisOf(result);
  if (analysis) return analysis.grammar;
  return result && "earlyGrammar" in result ? (result.earlyGrammar ?? []) : [];
}

// 지금 보일 번역과 루비
function translationOf(result: SentenceResult | undefined) {
  const analysis = analysisOf(result);
  if (analysis) return analysis;
  return result && "translation" in result ? result.translation : undefined;
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
  const analysis = analysisOf(result);
  const translation = translationOf(result);
  const grammar = grammarOf(result);
  const checking = checkingOf(result);
  return (
    <>
      <section className="sentence-card">
        <div className="display-toggles">
          {result?.status === "reanalyzing" && (
            <p role="status" aria-label="재분석 중" className="reanalysis">
              재분석 중
            </p>
          )}
          {result?.status === "failed" && result.previous && (
            <p className="reanalysis error">재분석하지 못했습니다</p>
          )}
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
            grammar={grammar}
            checking={checking}
            ruby={showRuby && translation ? translation.ruby : []}
            dragHandles={showHandles ? selection : undefined}
          />
        </p>
        <hr />
        {(!result || result.status === "early") && (
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
      {!analysis && grammar.length + checking.length > 0 && (
        <div className="below-card">
          <GrammarCards
            text={text}
            grammar={grammar}
            checking={checking}
            selection={selection}
          />
        </div>
      )}
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
      {result?.status === "failed" && !analysis && translation && (
        <p className="error below-card">문법·단어를 분석하지 못했습니다</p>
      )}
      {analysis && (
        <>
          <div role="tablist" className="tabs">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "grammar"}
              onClick={() => onTabChange("grammar")}
            >
              문법 {analysis.grammar.length}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "words"}
              onClick={() => onTabChange("words")}
            >
              단어 {analysis.words.length}
            </button>
          </div>
          <div role="tabpanel">
            {tab === "grammar" ? (
              <GrammarCards
                text={text}
                grammar={analysis.grammar}
                selection={selection}
              />
            ) : (
              <WordList words={analysis.words} selection={selection} />
            )}
          </div>
        </>
      )}
    </>
  );
}
