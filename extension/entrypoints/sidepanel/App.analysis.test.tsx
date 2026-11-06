import { expect, test, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import App from "./App";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { requestAnalysis } from "@/utils/analysis-request";
import {
  analysis,
  grammarItem,
  json,
  ndjson,
  panelWindowId,
  respondPerSentence,
  respondWith,
  rubies,
  rubyItem,
  send,
  streamed,
  wordItem,
} from "./app-test-support";

// 지정한 이름 API(#136)는 분석 요청의 fetch 가짜와 섞이지 않게 따로 가짜로 둔다.
vi.mock("@/utils/my-items", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/my-items")>()),
  fetchMyItems: vi.fn(),
  saveMyItem: vi.fn(),
}));

vi.mock("@/utils/names", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/names")>()),
  fetchNames: vi.fn(),
  saveName: vi.fn(),
  removeName: vi.fn(),
}));

test("분석 요청을 받으면 원문을 보이고, 응답 전에는 번역 자리에 스켈레톤을 보인다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  expect(await screen.findByText("私は学生です。")).toBeInTheDocument();
  expect(
    screen.getByRole("status", { name: "번역을 불러오는 중" }),
  ).toBeInTheDocument();
});

test("응답이 오면 번역을 보인다", async () => {
  const fetchMock = respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  expect(
    screen.queryByRole("status", { name: "번역을 불러오는 중" }),
  ).not.toBeInTheDocument();
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toMatch(/\/api\/analyses\/$/);
  expect(JSON.parse(init.body as string)).toEqual({ text: "私は学生です。" });
});

test("패널이 열리기 전에 들어온 분석 요청도 보인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [],
    words: [],
  });
  await send(panelWindowId, "私は学生です。");

  render(<App />);

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
});

test("실패 응답이면 '분석하지 못했습니다'를 보인다", async () => {
  respondWith(502, { error: "analysis_failed" });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();
});

test("서버에 연결하지 못하면 '분석하지 못했습니다'를 보인다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
  );
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();
});

test("다른 창의 분석 요청은 받지 않는다", async () => {
  const fetchMock = respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [],
    words: [],
  });
  const otherWindow = await fakeBrowser.windows.create({ focused: false });
  render(<App />);

  await send(otherWindow!.id!, "私は学生です。");
  await send(panelWindowId, "猫が好きです。");

  expect(await screen.findByText("猫が好きです。")).toBeInTheDocument();
  expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("패널을 다시 열어도 이미 분석한 요청은 다시 분석하지 않는다", async () => {
  const fetchMock = respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [],
    words: [],
  });
  const { unmount } = render(<App />);
  await send(panelWindowId, "私は学生です。");
  await screen.findByText("나는 학생입니다.");
  unmount();

  render(<App />);

  await waitFor(() =>
    expect(fakeBrowser.storage.session.get()).resolves.toEqual({}),
  );
  expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("저장소 읽기와 변경 알림이 같은 요청을 함께 전달해도 한 번만 분석한다", async () => {
  const fetchMock = respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [],
    words: [],
  });
  // 패널이 저장소를 읽는 사이에 요청이 들어와, 읽기 결과에도 그 요청이 담기는 경우
  let finishGet: (stored: Record<string, unknown>) => void = () => {};
  const getSpy = vi
    .spyOn(fakeBrowser.storage.session, "get")
    .mockReturnValue(new Promise((resolve) => (finishGet = resolve)) as never);
  const setSpy = vi.spyOn(fakeBrowser.storage.session, "set");
  render(<App />);
  await waitFor(() => expect(getSpy).toHaveBeenCalled());

  await send(panelWindowId, "私は学生です。");
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  // 실제 크롬 저장소처럼 읽을 때마다 새 객체를 돌려준다.
  finishGet(structuredClone(setSpy.mock.calls[0]![0]));

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("새 요청을 받은 뒤 늦게 끝난 초기 조회는 최신 문장을 바꾸지 않는다", async () => {
  const fetchMock = respondWith(200, analysis("분석 완료"));
  await send(panelWindowId, "私は学生です。");
  const old = await fakeBrowser.storage.session.get();
  let finishGet!: (stored: Record<string, unknown>) => void;
  const getSpy = vi
    .spyOn(fakeBrowser.storage.session, "get")
    .mockReturnValueOnce(
      new Promise((resolve) => (finishGet = resolve)) as never,
    );
  render(<App />);
  await waitFor(() => expect(getSpy).toHaveBeenCalled());

  await send(panelWindowId, "猫が好きです。");
  await screen.findByText("분석 완료");
  await act(async () => finishGet(old));

  expect(screen.getByText("猫が好きです。")).toBeInTheDocument();
  expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("로그아웃 시각 조회가 역순으로 끝나도 최신 문장만 분석한다", async () => {
  const fetchMock = respondWith(200, analysis("분석 완료"));
  const sessionGet = vi.spyOn(fakeBrowser.storage.session, "get");
  render(<App />);
  await screen.findByRole("button", { name: "로그아웃" });
  await waitFor(() => expect(sessionGet).toHaveBeenCalled());
  const originalGet = fakeBrowser.storage.local.get.bind(
    fakeBrowser.storage.local,
  );
  const finishChecks: ((stored: Record<string, unknown>) => void)[] = [];
  vi.spyOn(fakeBrowser.storage.local, "get").mockImplementation((keys) =>
    keys === "signedOutAt"
      ? new Promise((resolve) => finishChecks.push(resolve))
      : originalGet(keys),
  );

  await send(panelWindowId, "私は学生です。");
  await send(panelWindowId, "猫が好きです。");
  expect(finishChecks).toHaveLength(2);
  await act(async () => finishChecks[1]!({}));
  await screen.findByText("분석 완료");
  await act(async () => finishChecks[0]!({}));

  expect(screen.getByText("猫が好きです。")).toBeInTheDocument();
  expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("닫힌 패널의 늦은 초기 조회는 다음 패널의 요청을 지우지 않는다", async () => {
  const fetchMock = respondWith(200, analysis("분석 완료"));
  await send(panelWindowId, "私は学生です。");
  const old = await fakeBrowser.storage.session.get();
  let finishGet!: (stored: Record<string, unknown>) => void;
  const getSpy = vi
    .spyOn(fakeBrowser.storage.session, "get")
    .mockReturnValueOnce(
      new Promise((resolve) => (finishGet = resolve)) as never,
    );
  const { unmount } = render(<App />);
  await waitFor(() => expect(getSpy).toHaveBeenCalled());
  unmount();

  await send(panelWindowId, "猫が好きです。");
  await act(async () => finishGet(old));
  render(<App />);

  expect(await screen.findByText("猫が好きです。")).toBeInTheDocument();
  await screen.findByText("분석 완료");
  expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("같은 문장과 시작 시각이어도 새 회차는 다시 분석한다", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(json(200, analysis("첫 번역")))
    .mockResolvedValueOnce(json(200, analysis("새 번역")));
  vi.stubGlobal("fetch", fetchMock);
  const startedAt = Date.now();
  const sentences = [{ text: "猫が好きです。" }];
  render(<App />);

  await requestAnalysis(panelWindowId, sentences, startedAt);
  await screen.findByText("첫 번역");
  await requestAnalysis(panelWindowId, sentences, startedAt);

  expect(await screen.findByText("새 번역")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("번역은 앞부분부터 늘어나다 검증한 번역으로 바뀐다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "私は学生です。");

  stream.push({
    type: "translation_partial",
    translation_ko: "나는",
    ruby: [],
  });
  expect(await screen.findByText("나는")).toBeInTheDocument();
  stream.push({
    type: "translation_partial",
    translation_ko: "나는 학생",
    ruby: [],
  });
  expect(await screen.findByText("나는 학생")).toBeInTheDocument();
  expect(screen.queryByText("나는")).not.toBeInTheDocument();

  stream.push({
    type: "translation",
    translation_ko: "나는 학생입니다.",
    ruby: [],
  });
  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  stream.end();
});

test("앞부분만 받고 실패하면 앞부분을 지우고 실패를 보인다", async () => {
  // 검증 전 앞부분이 확정 번역처럼 남지 않는다(#303).
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "3人で行く");

  stream.push({
    type: "translation_partial",
    translation_ko: "셋이서",
    ruby: [],
  });
  expect(await screen.findByText("셋이서")).toBeInTheDocument();
  stream.push({ type: "error", error: "ANALYSIS:FAILED" });
  stream.end();

  expect(await screen.findByText(/분석하지 못했습니다/)).toBeInTheDocument();
  expect(screen.queryByText("셋이서")).not.toBeInTheDocument();
});

test("여러 문장이면 문장마다 한 페이지씩 보이고, 이전·다음으로 넘긴다", async () => {
  respondPerSentence({
    "私は学生です。": () => json(200, analysis("나는 학생입니다.")),
    "猫が好きです。": () => json(200, analysis("고양이를 좋아합니다.")),
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。", "猫が好きです。");

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  expect(screen.getByText("1 / 2")).toBeInTheDocument();
  expect(screen.queryByText("猫が好きです。")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "이전 문장" })).toBeDisabled();

  fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));

  expect(screen.getByText("2 / 2")).toBeInTheDocument();
  expect(screen.getByText("고양이를 좋아합니다.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "다음 문장" })).toBeDisabled();
});

test("한 문장이 실패해도 다른 문장 결과가 보인다", async () => {
  respondPerSentence({
    "私は学生です。": () => json(502, { error: "ANALYSIS:FAILED" }),
    "猫が好きです。": () => json(200, analysis("고양이를 좋아합니다.")),
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。", "猫が好きです。");

  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));
  expect(await screen.findByText("고양이를 좋아합니다.")).toBeInTheDocument();
});

test("하루 사용량이나 동시 요청 상한에 걸리면 그 문구를 보인다", async () => {
  respondPerSentence({
    "私は学生です。": () => json(429, { error: "ANALYSIS:USAGE_LIMIT" }),
    "猫が好きです。": () => json(429, { error: "ANALYSIS:TOO_MANY_REQUESTS" }),
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。", "猫が好きです。");

  expect(
    await screen.findByText(
      "오늘 쓸 수 있는 분석량을 다 썼습니다. 내일 다시 시도해 주세요.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "다시 시도" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));
  expect(
    await screen.findByText(
      "동시에 분석하는 문장이 너무 많습니다. 잠시 뒤 다시 시도해 주세요.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText("분석하지 못했습니다")).not.toBeInTheDocument();
});

test("문장이 길이 상한을 넘으면 나눠서 드래그하라고 안내한다", async () => {
  respondPerSentence({
    "私は学生です。": () => json(413, { error: "ANALYSIS:TEXT_TOO_LONG" }),
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  expect(
    await screen.findByText(
      "문장이 너무 깁니다. 1,000자 이하로 나눠서 드래그해 주세요.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText("분석하지 못했습니다")).not.toBeInTheDocument();
});

test("작업이 시작할 때 하루 한도에 걸린 스트림 오류도 그 문구를 보인다", async () => {
  respondPerSentence({
    "私は学生です。": () =>
      ndjson([{ type: "error", error: "ANALYSIS:USAGE_LIMIT" }]),
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  expect(
    await screen.findByText(
      "오늘 쓸 수 있는 분석량을 다 썼습니다. 내일 다시 시도해 주세요.",
    ),
  ).toBeInTheDocument();
});

test("이전 회차의 늦은 응답이 현재 결과를 바꾸지 않는다", async () => {
  let finishOld: (response: Response) => void = () => {};
  respondPerSentence({
    // 이전 회차의 첫 문장과 이번 회차의 첫 문장이 같은 글자여도 회차가 다르다.
    "私は学生です。": () =>
      new Promise<Response>((resolve) => (finishOld = resolve)),
    "猫が好きです。": () => json(200, analysis("고양이를 좋아합니다.")),
  });
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

  await send(panelWindowId, "猫が好きです。");
  expect(await screen.findByText("고양이를 좋아합니다.")).toBeInTheDocument();
  finishOld(json(200, analysis("늦게 온 번역")));

  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(screen.queryByText("늦게 온 번역")).not.toBeInTheDocument();
  expect(screen.getByText("고양이를 좋아합니다.")).toBeInTheDocument();
});

test("서버에는 문장 분석 요청을 동시에 5개까지만 보내고, 끝나는 대로 다음 문장을 보낸다", async () => {
  let finishFirst: (response: Response) => void = () => {};
  const fetchMock = respondPerSentence({
    "一。": () => new Promise<Response>((resolve) => (finishFirst = resolve)),
  });
  render(<App />);

  await send(
    panelWindowId,
    "一。",
    "二。",
    "三。",
    "四。",
    "五。",
    "六。",
    "七。",
  );

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
  finishFirst(json(200, analysis("하나.")));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
});

test("새 회차가 와도 이전 회차의 진행 중인 요청까지 세어 5개를 넘기지 않고, 이전 회차의 남은 문장은 보내지 않는다", async () => {
  let finishFirst: (response: Response) => void = () => {};
  const fetchMock = respondPerSentence({
    "一。": () => new Promise<Response>((resolve) => (finishFirst = resolve)),
  });
  render(<App />);
  // 5개는 진행 중, 六·七은 아직 보내지 않은 채 다음 회차가 온다.
  await send(
    panelWindowId,
    "一。",
    "二。",
    "三。",
    "四。",
    "五。",
    "六。",
    "七。",
  );
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));

  await send(panelWindowId, "猫です。");
  // 새 회차가 패널에 들어온 뒤에도 이전 회차의 5개가 끝나지 않아 새 요청을 보내지 않는다.
  expect(await screen.findByText("猫です。")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(5);

  finishFirst(json(200, analysis("하나.")));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
  const sentTexts = fetchMock.mock.calls.map(
    ([, init]) => (JSON.parse(init.body as string) as { text: string }).text,
  );
  expect(sentTexts.at(-1)).toBe("猫です。");
  expect(sentTexts).not.toContain("六。");
});

test("한 회차에 같은 문장이 반복되면 한 번만 분석하고 결과를 함께 보인다", async () => {
  const fetchMock = respondPerSentence({
    "猫です。": () => json(200, analysis("고양이입니다.")),
  });
  render(<App />);

  await send(panelWindowId, "猫です。", "猫です。");

  expect(await screen.findByText("고양이입니다.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));
  expect(await screen.findByText("고양이입니다.")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("번역이 오면 먼저 보이고, 문법·단어 탭은 이어서 채운다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "私は学生です。");

  stream.push({
    type: "translation",
    translation_ko: "나는 학생입니다.",
    ruby: [rubyItem(0, 1, "わたし")],
  });

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  expect(rubies()).toEqual([["私", "わたし"]]);
  expect(screen.getByRole("status", { name: "분석 중" })).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();

  stream.push({
    type: "analysis",
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は")],
    words: [],
  });
  stream.end();

  expect(
    await screen.findByRole("tab", { name: "문법 1" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("status", { name: "분석 중" }),
  ).not.toBeInTheDocument();
  expect(rubies()).toEqual([["私", "わたし"]]);
});

test("번역 뒤에 문법·단어가 실패하면 번역은 그대로 두고 문법·단어 실패를 보인다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        ndjson([
          { type: "translation", translation_ko: "나는 학생입니다.", ruby: [] },
          { type: "error", error: "ANALYSIS:FAILED" },
        ]),
      ),
    ),
  );
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  expect(
    await screen.findByText("문법·단어를 분석하지 못했습니다"),
  ).toBeInTheDocument();
  expect(screen.getByText("나는 학생입니다.")).toBeInTheDocument();
  expect(screen.queryByText("분석하지 못했습니다")).not.toBeInTheDocument();
});

test("번역 전에 실패하면 '분석하지 못했습니다'를 보인다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(ndjson([{ type: "error", error: "ANALYSIS:FAILED" }])),
    ),
  );
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();
});

test("먼저 온 단어가 탭에 보이는 동안 탭 바로 밑 한 곳에 분석 중을 보인다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "学生が開いた");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [],
    words: [wordItem(0, 2, "学生", "がくせい")],
  });
  fireEvent.click(await screen.findByRole("tab", { name: "단어 1" }));
  const loading = () => screen.queryAllByRole("status", { name: "분석 중" });
  expect(loading()).toHaveLength(1);
  // 탭 목록 바로 다음에 두어 내용이 길어도 가려지지 않는다.
  expect(screen.getByRole("tablist").nextElementSibling).toBe(loading()[0]);
  expect(loading()[0]).toHaveTextContent("분석 중…");
  expect(
    within(screen.getByRole("tabpanel")).queryByRole("status", {
      name: "분석 중",
    }),
  ).not.toBeInTheDocument();

  stream.push({ type: "translation", translation_ko: "학생이", ruby: [] });
  await screen.findByText("학생이");
  expect(loading()).toHaveLength(1);

  stream.push({
    type: "analysis",
    translation_ko: "학생이",
    grammar: [],
    words: [wordItem(0, 2, "学生", "がくせい")],
  });
  stream.end();
  await waitFor(() => expect(loading()).toHaveLength(0));
});
