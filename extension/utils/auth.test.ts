import { beforeEach, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { saveToken, signOut, watchConnection } from "./auth";

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
