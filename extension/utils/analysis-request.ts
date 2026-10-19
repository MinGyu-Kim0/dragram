// 백그라운드가 넣은 분석 요청을 사이드 패널이 읽는다. 패널이 막 열려 메시지를 놓치지 않도록
// 메시지 대신 세션 저장소를 거친다. 창마다 키를 따로 두어 그 창의 패널만 요청을 받고,
// 패널은 요청을 꺼내면서 지워 다시 열 때 같은 요청을 또 분석하지 않는다.
function keyFor(windowId: number): string {
  return `analysisRequest:${windowId}`;
}

export interface AnalysisRequest {
  // 분석 회차. 같은 문장을 다시 골라도 새 요청으로 본다.
  id: string;
  text: string;
}

export async function requestAnalysis(
  windowId: number,
  text: string,
): Promise<void> {
  const request: AnalysisRequest = { id: crypto.randomUUID(), text };
  await browser.storage.session.set({ [keyFor(windowId)]: request });
}

// 이 창의 분석 요청을 받는다. 이미 들어와 있던 요청과 이후에 들어오는 요청을 모두 받는다.
export function receiveAnalysisRequests(
  windowId: number,
  onRequest: (request: AnalysisRequest) => void,
): () => void {
  const key = keyFor(windowId);
  // 저장소 읽기와 변경 알림이 같은 요청을 함께 전달할 수 있어 회차 ID로 한 번만 받는다.
  let lastId: string | undefined;
  const take = (stored: unknown) => {
    const request = stored as AnalysisRequest | undefined;
    if (!request || request.id === lastId) return;
    lastId = request.id;
    browser.storage.session.remove(key);
    onRequest(request);
  };
  const listener = (
    changes: Record<string, { newValue?: unknown }>,
    area: string,
  ) => {
    if (area === "session") take(changes[key]?.newValue);
  };
  // 리스너를 먼저 달아야, 저장소를 읽는 사이에 들어온 요청을 놓치지 않는다.
  browser.storage.onChanged.addListener(listener);
  browser.storage.session.get(key).then((stored) => take(stored[key]));
  return () => browser.storage.onChanged.removeListener(listener);
}
