import { useEffect, useState } from "react";
import {
  receiveAnalysisRequests,
  type AnalysisRequest,
} from "@/utils/analysis-request";
import { analyzeSentence, type Analysis } from "@/utils/api";
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
    // 모든 문장을 바로 분석하되 동시 요청 한도 안에서 보낸다. 같은 문장은 한 번만 분석하고
    // 결과를 함께 쓴다. 새 요청이 오면 이전 요청의 늦은 응답은 버리고 남은 문장도 보내지 않는다.
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
    const byText = new Map<string, Promise<Analysis>>();
    request.sentences.forEach(({ text }, index) => {
      let analysis = byText.get(text);
      if (!analysis) {
        analysis = limiter.schedule(
          () => analyzeSentence(text),
          () => !current,
        );
        byText.set(text, analysis);
      }
      analysis.then(
        (result) => save(index, { status: "done", analysis: result }),
        () => save(index, { status: "failed" }),
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
