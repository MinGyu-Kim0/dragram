import { useEffect, useState } from "react";
import {
  receiveAnalysisRequests,
  type AnalysisRequest,
} from "@/utils/analysis-request";
import { analyzeSentence } from "@/utils/api";
import { SentenceView, type ResultTab, type SentenceResult } from "./Sentence";

// 서버에 동시에 보내는 문장 분석 요청 수. 문장 수에는 상한이 없어서(#23), 긴 글을 골라도
// 서버에 한꺼번에 몰리지 않게 한다. 비용 제한은 사용자별 토큰 한도(#28)로 한다.
const MAX_CONCURRENT_REQUESTS = 3;

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
    // 모든 문장을 바로 분석하되 동시에 MAX_CONCURRENT_REQUESTS개까지만 보낸다.
    // 새 요청이 오면 이전 요청의 늦은 응답은 버리고 남은 문장도 보내지 않는다.
    let current = true;
    const requestId = request.id;
    let next = 0;
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
    const analyzeNext = () => {
      if (!current || next >= request.sentences.length) return;
      const index = next++;
      analyzeSentence(request.sentences[index]!.text)
        .then(
          (analysis) => save(index, { status: "done", analysis }),
          () => save(index, { status: "failed" }),
        )
        .finally(analyzeNext);
    };
    for (let i = 0; i < MAX_CONCURRENT_REQUESTS; i++) analyzeNext();
    return () => {
      current = false;
    };
  }, [request]);

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
          result={result}
          tab={tab}
          onTabChange={setTab}
        />
      )}
    </main>
  );
}

export default App;
