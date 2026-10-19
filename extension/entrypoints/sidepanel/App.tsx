import { useEffect, useState } from "react";
import {
  receiveAnalysisRequests,
  type AnalysisRequest,
} from "@/utils/analysis-request";
import { analyzeSentence, type Analysis } from "@/utils/api";

// 결과에 회차 ID를 붙여, 지금 요청의 결과만 보인다. 없으면 아직 불러오는 중이다.
type Result =
  | { requestId: string; status: "done"; analysis: Analysis }
  | { requestId: string; status: "failed" };

function App() {
  const [request, setRequest] = useState<AnalysisRequest>();
  const [result, setResult] = useState<Result>();

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
    // 새 요청이 오면 이전 요청의 늦은 응답은 버린다.
    let current = true;
    const requestId = request.id;
    analyzeSentence(request.text).then(
      (analysis) =>
        current && setResult({ requestId, status: "done", analysis }),
      () => current && setResult({ requestId, status: "failed" }),
    );
    return () => {
      current = false;
    };
  }, [request]);

  const shown = result?.requestId === request?.id ? result : undefined;

  return (
    <main>
      <h1>Dragram</h1>
      {request && (
        <section className="sentence-card">
          <p lang="ja" className="original">
            {request.text}
          </p>
          <hr />
          {!shown && (
            <div
              role="status"
              aria-label="번역을 불러오는 중"
              className="skeleton"
            >
              <span />
              <span />
            </div>
          )}
          {shown?.status === "done" && (
            <p className="translation">{shown.analysis.translation_ko}</p>
          )}
          {shown?.status === "failed" && (
            <p className="error">분석하지 못했습니다</p>
          )}
        </section>
      )}
    </main>
  );
}

export default App;
