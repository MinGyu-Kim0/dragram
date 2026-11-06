import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { watchUpdateRequired } from "@/utils/api";
import { useUpdateRequired } from "./use-update-required";

vi.mock("@/utils/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/api")>()),
  watchUpdateRequired: vi.fn(),
}));

let serverRefused: () => void;
const stop = vi.fn();

beforeEach(() => {
  stop.mockReset();
  vi.mocked(watchUpdateRequired).mockImplementation((onUpdateRequired) => {
    serverRefused = onUpdateRequired;
    return stop;
  });
});

test("서버가 이 버전을 거부하기 전에는 업데이트를 요구하지 않는다", () => {
  const { result } = renderHook(() => useUpdateRequired());

  expect(result.current).toBe(false);
});

test("서버가 이 버전을 거부하면 업데이트를 요구한다", () => {
  const { result } = renderHook(() => useUpdateRequired());

  act(() => serverRefused());

  expect(result.current).toBe(true);
});

test("패널을 닫으면 감시를 멈춘다", () => {
  const { unmount } = renderHook(() => useUpdateRequired());

  unmount();

  expect(stop).toHaveBeenCalled();
});
