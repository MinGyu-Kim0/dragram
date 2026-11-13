import { vi } from "vitest";

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * fetch를 `"METHOD url"` 키로 응답을 고르는 대역으로 바꾼다.
 * 요청을 어떤 모양으로 남길지는 테스트마다 달라 `record`로 받는다.
 */
export function stubFetch(
  responses: Record<string, () => Response | Promise<Response>>,
  record: (url: string, method: string, init: RequestInit) => void,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      record(url, method, init);
      const respond = responses[`${method} ${url}`];
      if (!respond) throw new Error(`응답 없음: ${method} ${url}`);
      return respond();
    }),
  );
}
