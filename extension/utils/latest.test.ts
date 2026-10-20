import { expect, test } from "vitest";
import { latestPerKey } from "./latest";

test("같은 키에서는 가장 최근에 시작한 작업만 최신이다", () => {
  const start = latestPerKey();

  const first = start(1);
  const second = start(1);

  expect(first()).toBe(false);
  expect(second()).toBe(true);
});

test("키가 다르면 서로 영향을 주지 않는다", () => {
  const start = latestPerKey();

  const inWindow1 = start(1);
  const inWindow2 = start(2);

  expect(inWindow1()).toBe(true);
  expect(inWindow2()).toBe(true);
});
