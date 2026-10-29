import { render } from "@testing-library/react";
import { expect, test } from "vitest";

// 두 테스트는 순서대로 돈다. 앞 테스트가 그린 화면이 다음 테스트에 남으면 안 된다.
test("화면을 그린다", () => {
  render(<p>앞 테스트의 화면</p>);
});

test("앞 테스트의 화면이 남아 있지 않다", () => {
  expect(document.body).toBeEmptyDOMElement();
});

// 앞 테스트가 끝난 뒤 늦게 부른 fetch가 진짜 서버로 나가면, 로컬 백엔드의 401이 다음 테스트의
// 토큰을 지운다.
test("가짜로 바꾸지 않은 fetch는 서버로 나가지 않고 실패한다", async () => {
  await expect(fetch("http://localhost:8000/api/analyses/")).rejects.toThrow(
    "테스트에서 진짜 fetch를 불렀습니다",
  );
});
