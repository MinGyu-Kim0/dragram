import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { LoginRequired } from "./api";
import { loadToken, saveToken } from "./auth";
import { fetchMyItems, removeMyItem, saveMyItem } from "./my-items";

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

test("내 항목 목록을 확장 토큰으로 받는다", async () => {
  const fetchMock = respond(200, {
    items: [{ kind: "usage", id: 7, state: "hidden" }],
  });

  expect(await fetchMyItems()).toEqual([
    { kind: "usage", id: 7, state: "hidden" },
  ]);
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toMatch(/\/api\/my-items\/$/);
  expect((init.headers as Record<string, string>).Authorization).toBe(
    "Bearer extension-token",
  );
});

test("예문은 고를 때만 URL이 아닌 본문으로 보내고, 해제는 종류와 ID만 보낸다", async () => {
  let fetchMock = respond(200, { kind: "sense", id: 3, state: "added" });
  await saveMyItem("sense", 3, "added");
  expect(JSON.parse(fetchMock.mock.calls[0]![1].body as string)).toEqual({
    kind: "sense",
    id: 3,
    state: "added",
  });

  fetchMock = respond(200, { kind: "sense", id: 3, state: "added" });
  await saveMyItem("sense", 3, "added", {
    text: "毎朝走る。",
    start: 2,
    end: 4,
  });
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(init.method).toBe("PUT");
  expect(url).not.toContain(encodeURIComponent("毎朝"));
  expect(JSON.parse(init.body as string)).toEqual({
    kind: "sense",
    id: 3,
    state: "added",
    example: "毎朝走る。",
    example_start: 2,
    example_end: 4,
  });

  fetchMock = respond(204);
  await removeMyItem("usage", 7);
  expect(fetchMock.mock.calls[0]![1].method).toBe("DELETE");
  expect(JSON.parse(fetchMock.mock.calls[0]![1].body as string)).toEqual({
    kind: "usage",
    id: 7,
  });
});

test("401이면 토큰을 지우고 로그인이 필요하다고 알린다", async () => {
  respond(401, { error: "AUTH:LOGIN_REQUIRED" });

  await expect(fetchMyItems()).rejects.toBeInstanceOf(LoginRequired);
  expect(await loadToken()).toBeUndefined();
});
