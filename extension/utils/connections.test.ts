import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { LoginRequired } from "./api";
import { loadToken, saveToken } from "./auth";
import { fetchConnection } from "./connections";

beforeEach(async () => {
  fakeBrowser.reset();
  await saveToken("extension-token");
});
afterEach(() => vi.unstubAllGlobals());

function respond(status: number, result: object) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(result), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

test("패턴 ID와 확장 토큰으로만 요청하고 저장된 접속 정보를 받는다", async () => {
  const result = {
    pattern_id: 42,
    text: "동사 て형 + いる",
    review_status: "pending",
    filled: true,
  };
  const fetchMock = respond(200, result);

  expect(await fetchConnection(42)).toEqual(result);
  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringMatching(/\/api\/grammar-patterns\/42\/connection\/$/),
    {
      method: "POST",
      headers: { Authorization: "Bearer extension-token" },
    },
  );
});

test.each([429, 200])(
  "HTTP 오류와 응답을 시작한 뒤의 오류를 모두 거부한다(%s)",
  async (status) => {
    respond(status, { error: "ANALYSIS:FAILED" });
    await expect(fetchConnection(42)).rejects.toThrow();
    expect(await loadToken()).toBe("extension-token");
  },
);

test("401이면 토큰을 지우고 로그인 필요로 처리한다", async () => {
  respond(401, { error: "AUTH:LOGIN_REQUIRED" });
  await expect(fetchConnection(42)).rejects.toBeInstanceOf(LoginRequired);
  expect(await loadToken()).toBeUndefined();
});
