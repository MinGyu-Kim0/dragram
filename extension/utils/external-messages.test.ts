import { beforeEach, expect, test } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { loadToken, saveToken } from "./auth";
import { handleExternalMessage, WEB_ORIGIN } from "./external-messages";

beforeEach(() => {
  fakeBrowser.reset();
});

test("우리 웹의 connect 메시지는 토큰을 저장하고 받았다고 답한다", async () => {
  const reply = handleExternalMessage(
    { type: "connect", token: "extension-token", account: "me@example.com" },
    `${WEB_ORIGIN}/connect`,
  );

  expect(await reply).toEqual({ ok: true });
  expect(await loadToken()).toBe("extension-token");
});

test("우리 웹의 disconnect 메시지는 저장한 토큰을 지운다", async () => {
  await saveToken("extension-token");

  const reply = handleExternalMessage(
    { type: "disconnect" },
    `${WEB_ORIGIN}/connect`,
  );

  expect(await reply).toEqual({ ok: true });
  expect(await loadToken()).toBeUndefined();
});

test.each([
  "https://evil.example/connect",
  // 출처는 스킴·호스트·포트가 모두 같아야 한다.
  WEB_ORIGIN.replace("http://", "https://") + "/connect",
  undefined,
  "not a url",
])("다른 출처(%s)의 메시지는 무시한다", async (url) => {
  await saveToken("kept-token");

  expect(
    handleExternalMessage(
      { type: "connect", token: "stolen", account: "x@example.com" },
      url,
    ),
  ).toBeUndefined();
  expect(handleExternalMessage({ type: "disconnect" }, url)).toBeUndefined();
  expect(await loadToken()).toBe("kept-token");
});

test.each([
  { type: "connect" },
  { type: "connect", token: "" },
  { type: "connect", token: 42, account: "me@example.com" },
  { type: "connect", token: "extension-token" },
  { type: "unknown" },
  "connect",
  null,
])("모양이 맞지 않는 메시지(%j)는 거절한다", async (message) => {
  const reply = handleExternalMessage(message, `${WEB_ORIGIN}/connect`);

  expect(await reply).toEqual({ ok: false });
  expect(await loadToken()).toBeUndefined();
});
