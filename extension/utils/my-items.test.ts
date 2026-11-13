import { expect, test } from "vitest";
import { LoginRequired } from "./api";
import { loadToken } from "./auth";
import { fetchMyItems, saveMyItem } from "./my-items";
import { respond } from "./test-support";

test("내 항목 목록을 확장 토큰으로 받는다", async () => {
  const fetchMock = respond(200, {
    items: [{ kind: "usage", id: 7, added: false, hidden: true }],
  });

  expect(await fetchMyItems()).toEqual([
    { kind: "usage", id: 7, added: false, hidden: true },
  ]);
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toMatch(/\/api\/my-items\/$/);
  expect((init.headers as Record<string, string>).Authorization).toBe(
    "Bearer extension-token",
  );
});

test("바꿀 축만 보내고, 예문은 고를 때만 URL이 아닌 본문으로 보낸다", async () => {
  const added = { kind: "sense", id: 3, added: true, hidden: false };
  let fetchMock = respond(200, added);
  await saveMyItem("sense", 3, { hidden: false });
  expect(JSON.parse(fetchMock.mock.calls[0]![1].body as string)).toEqual({
    kind: "sense",
    id: 3,
    hidden: false,
  });

  fetchMock = respond(200, added);
  await saveMyItem(
    "sense",
    3,
    { added: true },
    {
      text: "毎朝走る。",
      start: 2,
      end: 4,
    },
  );
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(init.method).toBe("PUT");
  expect(url).not.toContain(encodeURIComponent("毎朝"));
  expect(JSON.parse(init.body as string)).toEqual({
    kind: "sense",
    id: 3,
    added: true,
    example: "毎朝走る。",
    example_start: 2,
    example_end: 4,
  });
});

test("401이면 토큰을 지우고 로그인이 필요하다고 알린다", async () => {
  respond(401, { error: "AUTH:LOGIN_REQUIRED" });

  await expect(fetchMyItems()).rejects.toBeInstanceOf(LoginRequired);
  expect(await loadToken()).toBeUndefined();
});
