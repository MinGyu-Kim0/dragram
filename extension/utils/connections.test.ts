import { expect, test } from "vitest";
import { LoginRequired } from "./api";
import { loadToken } from "./auth";
import { fetchConnection } from "./connections";
import { respond } from "../utils-test-support";

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
      headers: {
        Authorization: "Bearer extension-token",
        "X-Dragram-Version": "0.3.0",
      },
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
