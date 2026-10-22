import { useEffect, useState } from "react";
import {
  receiveAnalysisRequests,
  type AnalysisRequest,
} from "@/utils/analysis-request";
import {
  AnalysisFailed,
  analyzeSentence,
  type Analysis,
  type CheckingItem,
  type GrammarItem,
} from "@/utils/api";
import { createLimiter } from "@/utils/limiter";
import { SentenceView, type ResultTab, type SentenceResult } from "./Sentence";
import { usePreference } from "./use-preference";

// 서버에 동시에 보내는 문장 분석 요청 수. 문장 수에는 상한이 없어서(#23), 긴 글을 골라도
// 서버에 한꺼번에 몰리지 않게 한다. 회차가 바뀌어도 이전 회차의 진행 중인 요청까지 센다.
// 비용은 사용자별 토큰 한도로, 서버 쪽 동시 요청 제한은 #28에서 한다.
const MAX_CONCURRENT_REQUESTS = 5;

// 결과와 페이지에 회차 ID를 붙여, 지금 요청의 것만 쓴다.
interface Results {
  requestId: string;
  bySentence: Record<number, SentenceResult>;
}

interface Page {
  requestId: string;
  index: number;
}

function App() {
  const [request, setRequest] = useState<AnalysisRequest>();
  const [results, setResults] = useState<Results>();
  const [page, setPage] = useState<Page>();
  const [tab, setTab] = useState<ResultTab>("grammar");
  const [showHandles, toggleHandles] = usePreference("showDragHandles");
  const [showRuby, toggleRuby] = usePreference("showRuby");
  // 패널 하나에서 모든 회차가 함께 쓰는 동시 요청 한도
  const [limiter] = useState(() => createLimiter(MAX_CONCURRENT_REQUESTS));

  useEffect(() => {
    // 이 패널이 열린 창의 요청만 받는다.
    let active = true;
    let stop: (() => void) | undefined;
    browser.windows.getCurrent().then((window) => {
      if (active && window.id !== undefined) {
        stop = receiveAnalysisRequests(window.id, setRequest);
      }
    });
    return () => {
      active = false;
      stop?.();
    };
  }, []);

  useEffect(() => {
    if (!request) return;
    // 모든 문장을 바로 분석하되 동시 요청 한도 안에서 보낸다. 번역이 오면 먼저 보이고
    // 문법·단어가 오면 채운다. 같은 문장은 한 번만 분석하고 결과를 함께 쓴다.
    // 새 요청이 오면 이전 요청의 늦은 응답은 버리고 남은 문장도 보내지 않는다.
    let current = true;
    const requestId = request.id;
    const save = (index: number, result: SentenceResult) => {
      if (!current) return;
      setResults((previous) => ({
        requestId,
        bySentence: {
          ...(previous?.requestId === requestId ? previous.bySentence : {}),
          [index]: result,
        },
      }));
    };
    // 같은 문장은 한 번만 분석하고, 그 문장이 나온 모든 페이지에 결과를 넣는다.
    const indicesByText = new Map<string, number[]>();
    request.sentences.forEach(({ text }, index) => {
      indicesByText.set(text, [...(indicesByText.get(text) ?? []), index]);
    });
    indicesByText.forEach((indices, text) => {
      const saveAll = (result: SentenceResult) =>
        indices.forEach((index) => save(index, result));
      // LLM 없이 확정한 문법은 번역보다 먼저 와서, 번역이 와도 함께 보인다.
      let earlyGrammar: GrammarItem[] | undefined;
      let checking: CheckingItem[] | undefined;
      // stale 분석의 옛 결과. 있으면 새 결과가 다 올 때까지 그것만 보이고 중간 이벤트는 버린다.
      let previous: Analysis | undefined;
      limiter
        .schedule(
          () =>
            analyzeSentence(
              text,
              (translation) => {
                if (previous) return;
                saveAll({
                  status: "translated",
                  translation,
                  earlyGrammar,
                  checking,
                });
              },
              (grammar, waiting) => {
                if (previous) return;
                earlyGrammar = grammar;
                checking = waiting;
                saveAll({ status: "early", earlyGrammar, checking });
              },
              (old) => {
                previous = old;
                saveAll({ status: "reanalyzing", previous });
              },
            ),
          () => !current,
        )
        .then(
          (analysis) => saveAll({ status: "done", analysis }),
          (error: unknown) =>
            saveAll({
              status: "failed",
              // 다시 분석하다 실패하면 옛 결과만 남기고 그사이 받은 새 번역·문법은 버린다.
              ...(error instanceof AnalysisFailed
                ? error.previous
                  ? { previous: error.previous }
                  : {
                      translation: error.translation,
                      earlyGrammar: error.earlyGrammar,
                    }
                : {}),
            }),
        );
    });
    return () => {
      current = false;
    };
  }, [request, limiter]);

  const pageIndex = page && page.requestId === request?.id ? page.index : 0;
  const sentence = request?.sentences[pageIndex];
  const result =
    results && results.requestId === request?.id
      ? results.bySentence[pageIndex]
      : undefined;
  const goTo = (index: number) => setPage({ requestId: request!.id, index });

  return (
    <main>
      <h1>Dragram</h1>
      {request && request.sentences.length > 1 && (
        <nav className="pager" aria-label="문장">
          <button
            type="button"
            aria-label="이전 문장"
            disabled={pageIndex === 0}
            onClick={() => goTo(pageIndex - 1)}
          >
            ‹
          </button>
          <span>
            {pageIndex + 1} / {request.sentences.length}
          </span>
          <button
            type="button"
            aria-label="다음 문장"
            disabled={pageIndex === request.sentences.length - 1}
            onClick={() => goTo(pageIndex + 1)}
          >
            ›
          </button>
        </nav>
      )}
      {sentence && (
        <SentenceView
          text={sentence.text}
          selection={sentence.selection}
          showHandles={showHandles}
          onToggleHandles={toggleHandles}
          showRuby={showRuby}
          onToggleRuby={toggleRuby}
          result={result}
          tab={tab}
          onTabChange={setTab}
        />
      )}
    </main>
  );
}

export default App;
