import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { fetchNames, removeName, saveName } from "@/utils/names";
import { useDesignatedNames } from "./use-designated-names";
import { useLoginGeneration } from "./use-login-generation";

vi.mock("@/utils/names", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/names")>()),
  fetchNames: vi.fn(),
  saveName: vi.fn(),
  removeName: vi.fn(),
}));

const HARU = { surface: "春", reading: "はる" };
const AKI = { surface: "秋", reading: "あき" };

function setup(connected: boolean | undefined = true) {
  return renderHook(
    ({ connected }) => {
      const generation = useLoginGeneration();
      return { generation, ...useDesignatedNames(connected, generation) };
    },
    { initialProps: { connected } },
  );
}

beforeEach(() => {
  vi.mocked(fetchNames).mockReset().mockResolvedValue([]);
  vi.mocked(saveName).mockReset();
  vi.mocked(removeName).mockReset().mockResolvedValue(undefined);
});

test("연결되면 지정한 이름을 받아 표기에서 읽기를 찾게 한다", async () => {
  vi.mocked(fetchNames).mockResolvedValue([HARU]);

  const { result } = setup();

  await waitFor(() => expect(result.current.names.get("春")).toBe("はる"));
});

test("연결되기 전에는 받지 않는다", () => {
  setup(false);

  expect(fetchNames).not.toHaveBeenCalled();
});

test("저장하면 같은 표기의 이름을 새 읽기로 바꾼다", async () => {
  vi.mocked(fetchNames).mockResolvedValue([HARU]);
  vi.mocked(saveName).mockResolvedValue({ surface: "春", reading: "しゅん" });
  const { result } = setup();
  await waitFor(() => expect(result.current.names.size).toBe(1));

  await act(() => result.current.save("春", "しゅん"));

  expect([...result.current.names]).toEqual([["春", "しゅん"]]);
});

test("해제하면 그 표기를 뺀다", async () => {
  vi.mocked(fetchNames).mockResolvedValue([HARU, AKI]);
  const { result } = setup();
  await waitFor(() => expect(result.current.names.size).toBe(2));

  await act(() => result.current.remove("春"));

  expect([...result.current.names]).toEqual([["秋", "あき"]]);
});

test("목록을 받는 사이 저장했으면 받은 목록을 버리고 다시 받는다", async () => {
  let finishFirst!: (names: (typeof HARU)[]) => void;
  vi.mocked(fetchNames)
    .mockReturnValueOnce(new Promise((resolve) => (finishFirst = resolve)))
    .mockResolvedValueOnce([HARU, AKI]);
  vi.mocked(saveName).mockResolvedValue(AKI);
  const { result } = setup();

  await act(() => result.current.save("秋", "あき"));
  await act(async () => finishFirst([HARU]));

  await waitFor(() => expect(result.current.names.size).toBe(2));
  expect(fetchNames).toHaveBeenCalledTimes(2);
});

test("로그아웃한 뒤 늦게 끝난 저장은 다음 사람의 목록에 넣지 않는다", async () => {
  let finishSave!: (name: typeof HARU) => void;
  vi.mocked(saveName).mockReturnValue(
    new Promise((resolve) => (finishSave = resolve)),
  );
  const { result } = setup();
  await waitFor(() => expect(fetchNames).toHaveBeenCalled());

  let saving!: Promise<void>;
  act(() => {
    saving = result.current.save("春", "はる");
  });
  act(() => {
    result.current.clear();
    result.current.generation.advance();
  });
  await act(async () => {
    finishSave(HARU);
    await saving;
  });

  expect(result.current.names.size).toBe(0);
});

test("로그인 세대가 오르면 목록을 비운 뒤 새로 받는다", async () => {
  vi.mocked(fetchNames).mockResolvedValueOnce([HARU]).mockResolvedValueOnce([]);
  const { result } = setup();
  await waitFor(() => expect(result.current.names.size).toBe(1));

  act(() => {
    result.current.clear();
    result.current.generation.advance();
  });

  expect(result.current.names.size).toBe(0);
  await waitFor(() => expect(fetchNames).toHaveBeenCalledTimes(2));
});
