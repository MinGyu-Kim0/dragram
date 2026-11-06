import { act, renderHook } from "@testing-library/react";
import { expect, test } from "vitest";
import { useLoginGeneration } from "./use-login-generation";

test("로그아웃으로 세대가 오르면 값과 바로 읽는 참조가 함께 오른다", () => {
  const { result } = renderHook(() => useLoginGeneration());
  expect(result.current.value).toBe(0);

  act(() => result.current.advance());

  expect(result.current.value).toBe(1);
  expect(result.current.ref.current).toBe(1);
});

test("늦은 응답은 다시 그리기 전에도 오른 세대를 본다", () => {
  const { result } = renderHook(() => useLoginGeneration());
  let seen: number | undefined;

  act(() => {
    result.current.advance();
    seen = result.current.ref.current;
  });

  expect(seen).toBe(1);
});

test("세대를 올리는 함수는 다시 그려도 그대로라 연결 감시를 다시 걸지 않는다", () => {
  const { result, rerender } = renderHook(() => useLoginGeneration());
  const { advance } = result.current;

  rerender();

  expect(result.current.advance).toBe(advance);
});
