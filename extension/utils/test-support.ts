// 토큰으로 서버를 부르는 utils 테스트의 공통 준비. 가져오기만 하면 준비(저장소 비우기, 토큰
// 저장)와 정리(fetch 대역 풀기)가 함께 걸린다.
import { afterEach, beforeEach, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { saveToken } from "./auth";

beforeEach(async () => {
  fakeBrowser.reset();
  await saveToken("extension-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** fetch가 매번 `status`와 JSON 본문으로 답하게 바꾸고, 요청을 확인할 대역을 돌려준다. */
export function respond(status: number, body?: object) {
  const fetchMock = vi.fn((_url: string, _init: RequestInit) =>
    Promise.resolve(
      new Response(body && JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
