import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { requestAnalysis } from "@/utils/analysis-request";
import {
  AnalysisFailed,
  analyzeSentence,
  LoginRequired,
  type Analysis,
} from "@/utils/api";
import { saveToken } from "@/utils/auth";
import { useSentenceAnalysis } from "./use-sentence-analysis";

vi.mock("@/utils/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/api")>()),
  analyzeSentence: vi.fn(),
}));

function analysis(translation: string) {
  return {
    translation_ko: translation,
    grammar: [],
    words: [],
  } as unknown as Analysis;
}

let windowId: number;

const send = (...texts: string[]) =>
  act(() =>
    requestAnalysis(
      windowId,
      texts.map((text) => ({ text })),
    ),
  );

beforeEach(async () => {
  fakeBrowser.reset();
  windowId = (await fakeBrowser.windows.create({ focused: true }))!.id!;
  vi.mocked(analyzeSentence).mockReset();
});

test("요청을 받으면 문장마다 분석해 문장 번호로 결과를 찾게 한다", async () => {
  vi.mocked(analyzeSentence).mockImplementation(async (text) =>
    analysis(`${text} 번역`),
  );
  const { result } = renderHook(() => useSentenceAnalysis());

  await send("一", "二");

  await waitFor(() =>
    expect(result.current.resultAt(1)).toEqual({
      status: "done",
      analysis: analysis("二 번역"),
    }),
  );
  expect(result.current.resultAt(0)).toEqual({
    status: "done",
    analysis: analysis("一 번역"),
  });
  expect(result.current.request?.sentences).toHaveLength(2);
});

test("같은 문장은 한 번만 분석하고 나온 자리 모두에 결과를 넣는다", async () => {
  vi.mocked(analyzeSentence).mockResolvedValue(analysis("번역"));
  const { result } = renderHook(() => useSentenceAnalysis());

  await send("同じ", "同じ");

  await waitFor(() => expect(result.current.resultAt(1)?.status).toBe("done"));
  expect(result.current.resultAt(0)?.status).toBe("done");
  expect(analyzeSentence).toHaveBeenCalledTimes(1);
});

test("번역이 오면 완료 전에도 번역 상태로 보인다", async () => {
  vi.mocked(analyzeSentence).mockImplementation((_text, onTranslation) => {
    onTranslation({ translation_ko: "먼저 온 번역" } as never);
    return new Promise(() => {});
  });
  const { result } = renderHook(() => useSentenceAnalysis());

  await send("一");

  await waitFor(() =>
    expect(result.current.resultAt(0)).toMatchObject({
      status: "translated",
      translation: { translation_ko: "먼저 온 번역" },
    }),
  );
});

test("실패한 문장을 다시 시도하면 결과를 비우고 그 문장만 다시 분석한다", async () => {
  vi.mocked(analyzeSentence)
    .mockResolvedValueOnce(analysis("성공"))
    .mockRejectedValueOnce(new AnalysisFailed());
  const { result } = renderHook(() => useSentenceAnalysis());
  await send("一", "二");
  await waitFor(() =>
    expect(result.current.resultAt(1)?.status).toBe("failed"),
  );

  let finish!: (done: Analysis) => void;
  vi.mocked(analyzeSentence).mockReturnValueOnce(
    new Promise((resolve) => (finish = resolve)),
  );
  act(() => result.current.retry(1));

  expect(result.current.resultAt(1)).toBeUndefined();
  expect(result.current.resultAt(0)?.status).toBe("done");
  await act(async () => finish(analysis("다시 성공")));
  await waitFor(() => expect(result.current.resultAt(1)?.status).toBe("done"));
  expect(analyzeSentence).toHaveBeenCalledTimes(3);
});

test("새 회차가 오면 이전 회차의 늦은 응답은 버린다", async () => {
  let finishOld!: (done: Analysis) => void;
  vi.mocked(analyzeSentence)
    .mockReturnValueOnce(new Promise((resolve) => (finishOld = resolve)))
    .mockResolvedValueOnce(analysis("새 번역"));
  const { result } = renderHook(() => useSentenceAnalysis());
  await send("옛");
  await waitFor(() => expect(analyzeSentence).toHaveBeenCalledTimes(1));

  await send("새");
  await waitFor(() => expect(result.current.resultAt(0)?.status).toBe("done"));
  await act(async () => finishOld(analysis("옛 번역")));

  expect(result.current.resultAt(0)).toEqual({
    status: "done",
    analysis: analysis("새 번역"),
  });
});

test("로그인이 필요했던 요청은 연결되면 새 회차로 처음부터 다시 분석한다", async () => {
  vi.mocked(analyzeSentence)
    .mockRejectedValueOnce(new LoginRequired())
    .mockResolvedValueOnce(analysis("번역"));
  const { result } = renderHook(() => useSentenceAnalysis());
  await send("一");
  await waitFor(() => expect(analyzeSentence).toHaveBeenCalledTimes(1));
  const firstId = result.current.request?.id;

  await act(() => saveToken("token"));
  act(() => result.current.resumeAfterLogin());

  await waitFor(() => expect(result.current.resultAt(0)?.status).toBe("done"));
  expect(result.current.request?.id).not.toBe(firstId);
});

test("기다리는 요청이 없으면 연결돼도 다시 분석하지 않는다", async () => {
  vi.mocked(analyzeSentence).mockResolvedValue(analysis("번역"));
  const { result } = renderHook(() => useSentenceAnalysis());
  await send("一");
  await waitFor(() => expect(result.current.resultAt(0)?.status).toBe("done"));

  act(() => result.current.resumeAfterLogin());

  expect(analyzeSentence).toHaveBeenCalledTimes(1);
});

test("비우면 요청과 결과를 지우고 늦은 응답도 버린다", async () => {
  let finish!: (done: Analysis) => void;
  vi.mocked(analyzeSentence).mockReturnValue(
    new Promise((resolve) => (finish = resolve)),
  );
  const { result } = renderHook(() => useSentenceAnalysis());
  await send("一");
  await waitFor(() => expect(analyzeSentence).toHaveBeenCalled());

  act(() => result.current.clear());
  await act(async () => finish(analysis("늦은 번역")));

  expect(result.current.request).toBeUndefined();
  expect(result.current.resultAt(0)).toBeUndefined();
});
