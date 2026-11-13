import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { usePreference } from "./use-preference";

function storedLater<T>() {
  let resolve!: (value: T) => void;
  const load = vi.fn(() => new Promise<T>((r) => (resolve = r)));
  return { load, resolve: (value: T) => resolve(value) };
}

test("저장값을 읽기 전에는 처음 값이고, 읽으면 저장값이다", async () => {
  const { load, resolve } = storedLater<boolean>();
  const { result } = renderHook(() => usePreference(load, vi.fn(), true));

  expect(result.current[0]).toBe(true);
  await act(async () => resolve(false));
  expect(result.current[0]).toBe(false);
});

test("저장값을 읽기 전에 사용자가 바꾸면 늦게 읽힌 저장값으로 덮지 않는다", async () => {
  const { load, resolve } = storedLater<string>();
  const save = vi.fn(async () => {});
  const { result } = renderHook(() => usePreference(load, save, "marker"));

  act(() => result.current[1]("underline"));
  await act(async () => resolve("marker"));

  expect(result.current[0]).toBe("underline");
  expect(save).toHaveBeenCalledWith("underline");
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
});
