import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { fetchMyItems, markItemsChanged, saveMyItem } from "@/utils/my-items";
import { useLoginGeneration } from "./use-login-generation";
import { useMyItemStates } from "./use-my-item-states";

vi.mock("@/utils/my-items", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/my-items")>()),
  fetchMyItems: vi.fn(),
  saveMyItem: vi.fn(),
}));

type Listed = Awaited<ReturnType<typeof fetchMyItems>>[number];
type Saved = Awaited<ReturnType<typeof saveMyItem>>;

function listed(id: number, fields: Partial<Listed>) {
  return {
    kind: "sense",
    id,
    added: false,
    hidden: false,
    has_examples: false,
    ...fields,
  } as Listed;
}

function setup(connected: boolean | undefined = true) {
  return renderHook(
    ({ connected }) => {
      const generation = useLoginGeneration();
      return { generation, ...useMyItemStates(connected, generation) };
    },
    { initialProps: { connected } },
  );
}

beforeEach(() => {
  vi.mocked(fetchMyItems).mockReset().mockResolvedValue([]);
  vi.mocked(saveMyItem).mockReset();
});

test("연결되면 항목 상태와 예문이 있는 항목을 받는다", async () => {
  vi.mocked(fetchMyItems).mockResolvedValue([
    listed(1, { added: true, has_examples: true }),
    listed(2, { hidden: true }),
  ]);

  const { result } = setup();

  await waitFor(() => expect(result.current.items.states.size).toBe(2));
  expect(result.current.items.states.get("sense:1")).toEqual({
    added: true,
    hidden: false,
  });
  expect([...result.current.items.withExamples]).toEqual(["sense:1"]);
});

test("연결되기 전에는 받지 않는다", () => {
  setup(false);

  expect(fetchMyItems).not.toHaveBeenCalled();
});

test("저장하면 항목 상태를 바꾸고, 예문을 함께 저장했으면 예문 표시도 켠다", async () => {
  vi.mocked(saveMyItem).mockResolvedValue({
    added: true,
    hidden: false,
  } as Saved);
  const { result } = setup();

  await act(() =>
    result.current.items.save(
      "sense",
      7,
      { added: true },
      { text: "例", start: 0, end: 1 },
    ),
  );

  expect(result.current.items.states.get("sense:7")).toEqual({
    added: true,
    hidden: false,
  });
  expect(result.current.items.withExamples.has("sense:7")).toBe(true);
});

test("두 축이 모두 꺼지면 항목을 지우고 예문 표시도 지운다", async () => {
  vi.mocked(fetchMyItems).mockResolvedValue([
    listed(1, { added: true, has_examples: true }),
  ]);
  vi.mocked(saveMyItem).mockResolvedValue({
    added: false,
    hidden: false,
  } as Saved);
  const { result } = setup();
  await waitFor(() => expect(result.current.items.states.size).toBe(1));

  await act(() => result.current.items.save("sense", 1, { added: false }));

  expect(result.current.items.states.size).toBe(0);
  expect(result.current.items.withExamples.size).toBe(0);
});

test("같은 항목의 저장은 앞 요청이 끝난 뒤에 보낸다", async () => {
  let finishFirst!: (saved: Saved) => void;
  vi.mocked(saveMyItem)
    .mockReturnValueOnce(new Promise((resolve) => (finishFirst = resolve)))
    .mockResolvedValueOnce({ added: false, hidden: false } as Saved);
  const { result } = setup();

  let both!: Promise<unknown>;
  await act(async () => {
    both = Promise.all([
      result.current.items.save("sense", 1, { added: true }),
      result.current.items.save("sense", 1, { added: false }),
    ]);
    await Promise.resolve();
  });
  expect(saveMyItem).toHaveBeenCalledTimes(1);

  await act(async () => {
    finishFirst({ added: true, hidden: false } as Saved);
    await both;
  });

  expect(saveMyItem).toHaveBeenCalledTimes(2);
  expect(result.current.items.states.size).toBe(0);
});

test("기다리는 사이 로그아웃했으면 다음 저장을 보내지 않는다", async () => {
  let finishFirst!: (saved: Saved) => void;
  vi.mocked(saveMyItem).mockReturnValueOnce(
    new Promise((resolve) => (finishFirst = resolve)),
  );
  const { result } = setup();

  let both!: Promise<unknown>;
  await act(async () => {
    both = Promise.all([
      result.current.items.save("sense", 1, { added: true }),
      result.current.items.save("sense", 1, { hidden: true }),
    ]);
    await Promise.resolve();
  });
  act(() => {
    result.current.clear();
    result.current.generation.advance();
  });
  await act(async () => {
    finishFirst({ added: true, hidden: false } as Saved);
    await both;
  });

  expect(saveMyItem).toHaveBeenCalledTimes(1);
  expect(result.current.items.states.size).toBe(0);
});

test("웹에서 항목을 바꾸면 다시 받는다", async () => {
  const { result } = setup();
  await waitFor(() => expect(fetchMyItems).toHaveBeenCalledTimes(1));
  vi.mocked(fetchMyItems).mockResolvedValue([listed(1, { added: true })]);

  await act(() => markItemsChanged());

  await waitFor(() => expect(result.current.items.states.size).toBe(1));
  expect(fetchMyItems).toHaveBeenCalledTimes(2);
});
