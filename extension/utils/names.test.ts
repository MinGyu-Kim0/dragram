import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { LoginRequired } from "./api";
import { loadToken, saveToken } from "./auth";
import { fetchNames, isKana, removeName, saveName, toHiragana } from "./names";

beforeEach(async () => {
  fakeBrowser.reset();
  await saveToken("extension-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function respond(status: number, body?: object) {
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

test("지정한 이름 목록을 확장 토큰으로 받는다", async () => {
  const fetchMock = respond(200, {
    names: [{ surface: "春", reading: "はる" }],
  });

  expect(await fetchNames()).toEqual([{ surface: "春", reading: "はる" }]);
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toMatch(/\/api\/names\/$/);
  expect((init.headers as Record<string, string>).Authorization).toBe(
    "Bearer extension-token",
  );
});

test("저장과 해제는 표기를 URL이 아닌 본문으로 보낸다", async () => {
  const fetchMock = respond(200, { surface: "春", reading: "はる" });

  await saveName("春", "ハル");
  respond(204);
  await removeName("春");

  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).not.toContain(encodeURIComponent("春"));
  expect(init.method).toBe("PUT");
  expect(JSON.parse(init.body as string)).toEqual({
    surface: "春",
    reading: "ハル",
  });
});

test("401이면 토큰을 지우고 LoginRequired, 그 밖의 실패는 오류다", async () => {
  respond(400, { error: "NAME:INVALID" });
  await expect(saveName("春", "haru")).rejects.toThrow();
  expect(await loadToken()).toBe("extension-token");

  respond(401, { error: "AUTH:LOGIN_REQUIRED" });
  await expect(fetchNames()).rejects.toBeInstanceOf(LoginRequired);
  expect(await loadToken()).toBeUndefined();
});

test("가나 검사와 히라가나 변환은 서버 규칙과 같다", () => {
  expect(isKana("ハルー")).toBe(true);
  expect(isKana("haru")).toBe(false);
  expect(isKana("春")).toBe(false);
  expect(toHiragana("ハルカ")).toBe("はるか");
});
