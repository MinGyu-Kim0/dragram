import type {
  Analysis,
  CheckingItem,
  GrammarItem,
  Translation,
  WordItem,
} from "@/utils/api";
import type { DragRange } from "./drag-range";
import { GrammarCards, HighlightedText } from "./Grammar";
import { WordList } from "./Words";

// 문장 하나의 분석 결과. 없으면 아직 아무것도 오지 않았다. early는 번역보다 먼저 온
// grammar 이벤트(LLM 없이 확정한 문법 earlyGrammar, 판별 대상 구간 checking)만 와서
// 번역을 기다리는 중이다. translated는 번역이 와서 문법·단어를 기다리는 중이다. failed에 번역이
// 있으면 번역 뒤 문법·단어에서 실패했다. earlyGrammar는 analysis가 오기 전까지 보이고(judged
// 이벤트가 오면 첫 LLM 응답이 판정한 문법이 더해진다, #97), 실패하면 LLM 없이 확정한 문법만 남는다.
// checking은 실패하면 지운다. earlyWords는 같은 grammar 이벤트로 먼저 온 사전 단어(뜻을 준비하는
// 중인 단어 포함)와 judged 이벤트로 바뀐 단어(#97)이고, analysis가 오면 그 단어로 바뀌며 실패하면 지운다. reanalyzing은 stale 분석의 옛 결과(previous)를 보이며 새 결과를
// 기다리는 중(재분석 중)이고, 그러다 실패하면 failed에 옛 결과만 남는다.
export type SentenceResult =
  | {
      status: "early";
      earlyGrammar: GrammarItem[];
      checking: CheckingItem[];
      earlyWords?: WordItem[];
    }
  | {
      status: "translated";
      translation: Translation;
      earlyGrammar?: GrammarItem[];
      checking?: CheckingItem[];
      earlyWords?: WordItem[];
    }
  | { status: "done"; analysis: Analysis }
  | { status: "reanalyzing"; previous: Analysis }
  | {
      status: "failed";
      translation?: Translation;
      earlyGrammar?: GrammarItem[];
      previous?: Analysis;
      // 서버가 분석을 시작하기 전에 거부한 오류 코드
      code?: string;
    };

// 분석을 시작하기 전에 거부된 사유별 문구(#28). 그 밖의 실패는 '분석하지 못했습니다'다.
const REFUSALS: Record<string, string> = {
  "ANALYSIS:USAGE_LIMIT":
    "오늘 쓸 수 있는 분석량을 다 썼습니다. 내일 다시 시도해 주세요.",
  "ANALYSIS:TOO_MANY_REQUESTS":
    "동시에 분석하는 문장이 너무 많습니다. 잠시 뒤 다시 시도해 주세요.",
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

// 분석이 끝나기 전에 먼저 온 단어. 분석이 끝나거나 실패하면 없다.
function earlyWordsOf(result: SentenceResult | undefined) {
  if (result?.status === "early" || result?.status === "translated") {
    return result.earlyWords ?? [];
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

// 실패 문구 바로 옆에 두는 다시 시도 버튼
function RetryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <button type="button" className="retry" onClick={onRetry}>
      다시 시도
    </button>
  );
}

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
  onRetry,
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
  // 실패한 문장을 처음부터 다시 분석한다.
  onRetry: () => void;
}) {
  const analysis = analysisOf(result);
  const translation = translationOf(result);
  const grammar = grammarOf(result);
  const checking = checkingOf(result);
  const earlyWords = earlyWordsOf(result);
  // 탭에 보일 문법·단어. 분석이 끝나기 전에도 먼저 온 단어가 있으면 먼저 온 문법과 함께 탭으로
  // 보인다(#96). 문법 개수는 보이는 카드 수다(구성 문법의 하위 박스도 센다).
  const tabbed = analysis
    ? {
        grammar: analysis.grammar,
        checking: [],
        words: analysis.words,
        grammarCount: analysis.grammar.reduce(
          (count, item) => count + 1 + (item.parts?.length ?? 0),
          0,
        ),
      }
    : earlyWords.length > 0
      ? {
          grammar,
          checking,
          words: earlyWords,
          grammarCount: grammar.length + checking.length,
        }
      : undefined;
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
            <p className="reanalysis error">
              재분석하지 못했습니다 <RetryButton onRetry={onRetry} />
            </p>
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
          <p className="error">
            {REFUSALS[result.code ?? ""] ?? "분석하지 못했습니다"}{" "}
            <RetryButton onRetry={onRetry} />
          </p>
        )}
      </section>
      {!tabbed && grammar.length + checking.length > 0 && (
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
        <p className="error below-card">
          문법·단어를 분석하지 못했습니다 <RetryButton onRetry={onRetry} />
        </p>
      )}
      {tabbed && (
        <>
          <div role="tablist" className="tabs">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "grammar"}
              onClick={() => onTabChange("grammar")}
            >
              문법 {tabbed.grammarCount}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "words"}
              onClick={() => onTabChange("words")}
            >
              단어 {tabbed.words.length}
            </button>
          </div>
          <div role="tabpanel">
            {tab === "grammar" &&
            !analysis &&
            tabbed.grammar.length + tabbed.checking.length === 0 ? (
              // 단어만 먼저 왔다. 문법이 없다고 단정하지 않고 분석을 기다린다.
              <div
                role="status"
                aria-label="문법을 불러오는 중"
                className="skeleton below-card"
              >
                <span />
                <span />
              </div>
            ) : tab === "grammar" ? (
              <GrammarCards
                text={text}
                grammar={tabbed.grammar}
                checking={tabbed.checking}
                selection={selection}
              />
            ) : (
              <WordList words={tabbed.words} selection={selection} />
            )}
          </div>
        </>
      )}
    </>
  );
}
