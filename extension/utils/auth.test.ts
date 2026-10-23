import { beforeEach, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import {
  clearTokenIfStill,
  loadToken,
  saveToken,
  signOut,
  signOutIfStill,
  watchConnection,
} from "./auth";

beforeEach(() => {
  fakeBrowser.reset();
});

function watch() {
  const events: string[] = [];
  watchConnection({
    onConnected: (connected) => events.push(connected ? "connected" : "out"),
    onSignedOut: () => events.push("reset"),
  });
  return events;
}

test("처음 읽기가 끝나기 전에 연결 알림이 오면 늦은 처음 값은 버린다", async () => {
  let finishLoad!: (value: Record<string, unknown>) => void;
  vi.spyOn(fakeBrowser.storage.local, "get").mockReturnValueOnce(
    new Promise((resolve) => (finishLoad = resolve)) as never,
  );
  const events = watch();

  await saveToken("new-token");
  finishLoad({});
  await Promise.resolve();

  expect(events).toEqual(["connected"]);
});

test("로그아웃하면 화면을 비우라고 알리고 연결이 끊긴다", async () => {
  await saveToken("token");
  const events = watch();
  await vi.waitFor(() => expect(events).toEqual(["connected"]));

  await signOut();

  expect(events).toEqual(["connected", "reset", "out"]);
});

test("로그아웃 확인과 지우기 사이에 새 토큰이 저장돼도 새 토큰은 남는다", async () => {
  await saveToken("old-token");

  // 로그아웃이 먼저 시작하고, 끝나기 전에 웹 연결이 새 토큰을 저장한다.
  await Promise.all([signOutIfStill("old-token"), saveToken("new-token")]);

  expect(await loadToken()).toBe("new-token");
});

test("로그아웃은 표시와 토큰 지우기를 한 번에 저장한다", async () => {
  await saveToken("token");
  const set = vi.spyOn(fakeBrowser.storage.local, "set");
  const remove = vi.spyOn(fakeBrowser.storage.local, "remove");

  await signOut();

  expect(set).toHaveBeenCalledTimes(1);
  expect(remove).not.toHaveBeenCalled();
  expect(await loadToken()).toBeUndefined();
});

test("다른 계정이 연결하면 화면을 비우라고 알리고, 같은 계정의 재연결은 그대로 둔다", async () => {
  await saveToken("a-token", "a@example.com");
  const events = watch();
  await vi.waitFor(() => expect(events).toEqual(["connected"]));

  await saveToken("a-token-2", "a@example.com");
  expect(events).toEqual(["connected", "connected"]);

  await saveToken("b-token", "b@example.com");
  expect(events).toEqual(["connected", "connected", "reset", "connected"]);
});

test("401로 토큰만 지워진 뒤에 다른 계정이 연결해도 화면을 비우라고 알린다", async () => {
  await saveToken("a-token", "a@example.com");
  const events = watch();
  await vi.waitFor(() => expect(events).toEqual(["connected"]));
  await clearTokenIfStill("a-token");

  await saveToken("b-token", "b@example.com");

  expect(events).toEqual(["connected", "out", "reset", "connected"]);
});
