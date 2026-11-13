import { expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { analyzeSentence, logoutExtension, watchUpdateRequired } from "./api";
import { loadToken } from "./auth";
import { fetchConnection } from "./connections";
import { fetchMyItems } from "./my-items";
import { fetchNames } from "./names";
import { respond } from "./test-support";

// 확장이 서버로 보내는 모든 요청에 확장 버전을 붙이고, 서버가 업데이트를 요구하면 알린다(#349).

const requests = {
  분석: () => analyzeSentence("私は学生です。", () => {}),
  "내 일본어": () => fetchMyItems(),
  이름: () => fetchNames(),
  "접속 형태": () => fetchConnection(42),
  로그아웃: () => logoutExtension(),
};

test.each(Object.entries(requests))(
  "%s 요청에 manifest의 확장 버전을 붙인다",
  async (_, request) => {
    const fetchMock = respond(200, {});

    await request().catch(() => {});

    const [, init] = fetchMock.mock.calls[0]!;
    expect((init.headers as Record<string, string>)["X-Dragram-Version"]).toBe(
      fakeBrowser.runtime.getManifest().version,
    );
  },
);

test.each(Object.entries(requests).filter(([name]) => name !== "로그아웃"))(
  "%s 요청이 426이면 업데이트가 필요하다고 알리고 토큰은 남긴다",
  async (_, request) => {
    respond(426, { error: "EXTENSION:UPDATE_REQUIRED" });
    const onUpdateRequired = vi.fn();
    const stop = watchUpdateRequired(onUpdateRequired);

    await expect(request()).rejects.toThrow();

    stop();
    expect(onUpdateRequired).toHaveBeenCalledOnce();
    expect(await loadToken()).toBe("extension-token");
  },
);
