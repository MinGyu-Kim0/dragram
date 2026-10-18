// 백그라운드가 넣은 분석 요청을 사이드 패널이 읽는다. 패널이 막 열려 메시지를 놓치지 않도록
// 메시지 대신 세션 저장소를 거친다.
const KEY = "analysisRequest";

export interface AnalysisRequest {
  // 분석 회차. 같은 문장을 다시 골라도 새 요청으로 본다.
  id: string;
  text: string;
}

export async function requestAnalysis(text: string): Promise<void> {
  const request: AnalysisRequest = { id: crypto.randomUUID(), text };
  await browser.storage.session.set({ [KEY]: request });
}

export async function getAnalysisRequest(): Promise<
  AnalysisRequest | undefined
> {
  const stored = await browser.storage.session.get(KEY);
  return stored[KEY] as AnalysisRequest | undefined;
}

export function watchAnalysisRequest(
  onRequest: (request: AnalysisRequest) => void,
): () => void {
  const listener = (
    changes: Record<string, { newValue?: unknown }>,
    area: string,
  ) => {
    const request = changes[KEY]?.newValue;
    if (area === "session" && request) onRequest(request as AnalysisRequest);
  };
  browser.storage.onChanged.addListener(listener);
  return () => browser.storage.onChanged.removeListener(listener);
}
