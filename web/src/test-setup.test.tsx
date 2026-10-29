import { render } from "@testing-library/react";
import { expect, test } from "vitest";

// 두 테스트는 순서대로 돈다. 앞 테스트가 그린 화면이 다음 테스트에 남으면 안 된다.
test("화면을 그린다", () => {
  render(<p>앞 테스트의 화면</p>);
});

test("앞 테스트의 화면이 남아 있지 않다", () => {
  expect(document.body).toBeEmptyDOMElement();
});
