import { expect, test, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import App from "./App";
import {
  analysis,
  approvedGrammarItem,
  checkingItem,
  grammarItem,
  json,
  ndjson,
  panelWindowId,
  respondPerSentence,
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

const failed = () => json(502, { error: "ANALYSIS:FAILED" });

// stale 분석의 옛 결과(번역, 루비, 문법, 단어)
function previousEvent() {
  return {
    type: "previous",
    translation_ko: "그가 와 있다",
    ruby: [{ start: 2, end: 3, reading: "き" }],
    grammar: [grammarItem(3, 6, "진행")],
    words: [wordItem(0, 1, "彼", "かれ", {}, ["pronoun"])],
  };
}

test("stale 분석은 옛 결과를 '재분석 중'으로 먼저 보이고, 중간 이벤트는 반영하지 않다가 분석이 오면 새 결과로 바꾼다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "彼が来ている");

  stream.push(previousEvent());

  expect(
    await screen.findByRole("status", { name: "재분석 중" }),
  ).toHaveTextContent("재분석 중");
  expect(screen.getByText("그가 와 있다")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "문법 1" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "단어 1" })).toBeInTheDocument();
  expect(document.querySelector(".original rt")?.textContent).toBe("き");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [checkingItem(3, 6, "진행", "결과 상태")],
  });
  stream.push({ type: "translation", translation_ko: "새 번역", ruby: [] });
  await new Promise((resolve) => setTimeout(resolve, 0));

  // 옛 결과·탭이 그대로이고, 새 번역·확인 중·스켈레톤은 보이지 않는다.
  expect(screen.getByText("그가 와 있다")).toBeInTheDocument();
  expect(screen.queryByText("새 번역")).not.toBeInTheDocument();
  expect(screen.queryByText("확인 중")).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "문법 1" })).toBeInTheDocument();
  expect(
    screen.queryByRole("status", { name: "분석 중" }),
  ).not.toBeInTheDocument();

  stream.push({
    type: "analysis",
    translation_ko: "새 번역",
    grammar: [],
    words: [],
  });
  stream.end();

  expect(await screen.findByText("새 번역")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "문법 0" })).toBeInTheDocument();
  expect(screen.queryByText("재분석 중")).not.toBeInTheDocument();
});

test("재분석이 실패하면 옛 결과를 남기고 '재분석하지 못했습니다'를 보이며, 그사이 받은 새 번역은 버린다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        ndjson([
          previousEvent(),
          { type: "grammar", grammar: [], checking: [] },
          { type: "translation", translation_ko: "새 번역", ruby: [] },
          { type: "error", error: "ANALYSIS:FAILED" },
        ]),
      ),
    ),
  );
  render(<App />);

  await send(panelWindowId, "彼が来ている");

  expect(await screen.findByText("재분석하지 못했습니다")).toBeInTheDocument();
  expect(screen.queryByText("재분석 중")).not.toBeInTheDocument();
  expect(screen.getByText("그가 와 있다")).toBeInTheDocument();
  expect(screen.queryByText("새 번역")).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "문법 1" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "단어 1" })).toBeInTheDocument();
  expect(
    screen.queryByText("문법·단어를 분석하지 못했습니다"),
  ).not.toBeInTheDocument();
});

test("재분석 중에 스트림이 끊겨도 옛 결과를 남기고 '재분석하지 못했습니다'를 보인다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(ndjson([previousEvent()]))),
  );
  render(<App />);

  await send(panelWindowId, "彼が来ている");

  expect(await screen.findByText("재분석하지 못했습니다")).toBeInTheDocument();
  expect(screen.getByText("그가 와 있다")).toBeInTheDocument();
});

// 요청마다 차례로 다른 응답을 준다. 정한 응답이 다 떨어지면 응답하지 않는다.
function respondInTurn(...responses: (() => Promise<Response> | Response)[]) {
  const fetchMock = vi.fn((_url: string, _init: RequestInit) => {
    const respond = responses.shift();
    return respond
      ? Promise.resolve(respond())
      : new Promise<Response>(() => {});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// 첫 요청은 실패하고, 다음 요청부터는 then으로 응답한다.
function failOnceThen(then: () => Promise<Response> | Response) {
  let tried = false;
  return () => {
    if (tried) return then();
    tried = true;
    return failed();
  };
}

test("번역 전에 실패한 문장은 '다시 시도'로 그 문장만 다시 요청하고, 성공하면 결과로 바뀐다", async () => {
  const fetchMock = respondInTurn(failed, () =>
    json(200, analysis("나는 학생입니다.")),
  );
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "문법 0" })).toBeInTheDocument();
  expect(screen.queryByText("분석하지 못했습니다")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "다시 시도" }),
  ).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("번역 뒤에 실패한 문장에서 다시 시도하면 옛 번역이 사라지고 스켈레톤을 보인 뒤 새 결과로 바뀐다", async () => {
  const stream = streamed();
  respondInTurn(
    () =>
      ndjson([
        { type: "translation", translation_ko: "옛 번역", ruby: [] },
        { type: "error", error: "ANALYSIS:FAILED" },
      ]),
    () => stream.response,
  );
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  expect(
    await screen.findByText("문법·단어를 분석하지 못했습니다"),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));

  expect(
    await screen.findByRole("status", { name: "번역을 불러오는 중" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("옛 번역")).not.toBeInTheDocument();
  expect(
    screen.queryByText("문법·단어를 분석하지 못했습니다"),
  ).not.toBeInTheDocument();

  stream.push({ type: "translation", translation_ko: "새 번역", ruby: [] });
  stream.push({ type: "analysis", ...analysis("새 번역") });
  stream.end();

  expect(
    await screen.findByRole("tab", { name: "문법 0" }),
  ).toBeInTheDocument();
  expect(screen.getByText("새 번역")).toBeInTheDocument();
});

test("먼저 온 문법이 있는 채로 실패한 문장에서 다시 시도하면 그 카드도 지우고 다시 온 결과로 채운다", async () => {
  const stream = streamed();
  respondInTurn(
    () =>
      ndjson([
        { type: "grammar", grammar: [approvedGrammarItem(3, 6, "진행")] },
        { type: "error", error: "ANALYSIS:FAILED" },
      ]),
    () => stream.response,
  );
  render(<App />);
  await send(panelWindowId, "彼が来ている");
  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(1);

  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));

  await waitFor(() =>
    expect(screen.queryAllByRole("listitem")).toHaveLength(0),
  );
  stream.push({
    type: "grammar",
    grammar: [approvedGrammarItem(3, 6, "결과 상태")],
  });
  expect(
    within((await screen.findAllByRole("listitem"))[0]!).getByRole("heading")
      .textContent,
  ).toBe("결과 상태");
  stream.push({
    type: "translation",
    translation_ko: "그가 와 있다",
    ruby: [],
  });
  stream.push({
    type: "analysis",
    translation_ko: "그가 와 있다",
    grammar: [approvedGrammarItem(3, 6, "결과 상태")],
    words: [],
  });
  stream.end();

  expect(
    await screen.findByRole("tab", { name: "문법 1" }),
  ).toBeInTheDocument();
});

test("여러 문장 중 실패한 문장에만 버튼이 있고, 다시 시도해도 다른 문장은 다시 보내지 않는다", async () => {
  const fetchMock = respondPerSentence({
    "私は学生です。": failOnceThen(() =>
      json(200, analysis("나는 학생입니다.")),
    ),
    "猫が好きです。": () => json(200, analysis("고양이를 좋아합니다.")),
  });
  render(<App />);
  await send(panelWindowId, "私は学生です。", "猫が好きです。");
  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));
  expect(await screen.findByText("고양이를 좋아합니다.")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "다시 시도" }),
  ).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "이전 문장" }));
  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  const sentTexts = fetchMock.mock.calls.map(
    ([, init]) => (JSON.parse(init.body as string) as { text: string }).text,
  );
  expect(sentTexts.filter((text) => text === "猫が好きです。")).toHaveLength(1);
  expect(sentTexts.filter((text) => text === "私は学生です。")).toHaveLength(2);
});

test("분석 중이거나 번역만 온 문장에는 다시 시도 버튼이 없다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  expect(
    await screen.findByRole("status", { name: "번역을 불러오는 중" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "다시 시도" }),
  ).not.toBeInTheDocument();

  stream.push({
    type: "translation",
    translation_ko: "나는 학생입니다.",
    ruby: [],
  });

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "다시 시도" }),
  ).not.toBeInTheDocument();
});

test("다시 시도가 또 실패하면 실패 문구와 버튼이 다시 보이고 또 누를 수 있다", async () => {
  const fetchMock = respondInTurn(failed, failed, () =>
    json(200, analysis("나는 학생입니다.")),
  );
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  fireEvent.click(await screen.findByRole("button", { name: "다시 시도" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  fireEvent.click(await screen.findByRole("button", { name: "다시 시도" }));

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

test("같은 문장이 두 페이지에 있으면 한 페이지에서 다시 시도해도 요청은 한 번이고 두 페이지 모두 새 결과를 보인다", async () => {
  const fetchMock = respondInTurn(failed, () =>
    json(200, analysis("고양이입니다.")),
  );
  render(<App />);
  await send(panelWindowId, "猫です。", "猫です。");
  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));

  expect(await screen.findByText("고양이입니다.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));
  expect(await screen.findByText("고양이입니다.")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("다시 시도한 요청이 끝나기 전에 새 회차가 오면 그 응답은 새 회차 화면에 나타나지 않는다", async () => {
  let finishRetry: (response: Response) => void = () => {};
  respondPerSentence({
    "私は学生です。": failOnceThen(
      () => new Promise<Response>((resolve) => (finishRetry = resolve)),
    ),
    "猫が好きです。": () => json(200, analysis("고양이를 좋아합니다.")),
  });
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  fireEvent.click(await screen.findByRole("button", { name: "다시 시도" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));

  await send(panelWindowId, "猫が好きです。");
  expect(await screen.findByText("고양이를 좋아합니다.")).toBeInTheDocument();
  finishRetry(json(200, analysis("늦게 온 번역")));

  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(screen.queryByText("늦게 온 번역")).not.toBeInTheDocument();
  expect(screen.getByText("고양이를 좋아합니다.")).toBeInTheDocument();
});

test("다시 시도도 동시 요청 한도에 들어가, 한도가 차 있으면 자리가 날 때까지 보내지 않는다", async () => {
  let finishFirst: (response: Response) => void = () => {};
  const fetchMock = respondPerSentence({
    "一。": () => new Promise<Response>((resolve) => (finishFirst = resolve)),
    "二。": () => new Promise<Response>(() => {}),
    "三。": () => new Promise<Response>(() => {}),
    "四。": () => new Promise<Response>(() => {}),
    "五。": failOnceThen(() => json(200, analysis("다섯."))),
    "六。": () => new Promise<Response>(() => {}),
  });
  render(<App />);
  // 五가 실패해 자리가 나면 六이 들어가 다시 5개가 찬다.
  await send(panelWindowId, "一。", "二。", "三。", "四。", "五。", "六。");
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
  for (let i = 0; i < 4; i++) {
    fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));
  }
  fireEvent.click(await screen.findByRole("button", { name: "다시 시도" }));

  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(fetchMock).toHaveBeenCalledTimes(6);

  finishFirst(json(200, analysis("하나.")));
  expect(await screen.findByText("다섯.")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(7);
});

test("재분석이 실패한 문장에도 다시 시도 버튼이 있고, 누르면 그 문장만 다시 요청해 다시 '재분석 중'이 된다", async () => {
  const stream = streamed();
  const fetchMock = respondInTurn(
    () =>
      ndjson([previousEvent(), { type: "error", error: "ANALYSIS:FAILED" }]),
    () => stream.response,
  );
  render(<App />);
  await send(panelWindowId, "彼が来ている");
  expect(await screen.findByText("재분석하지 못했습니다")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));

  // 결과를 비우고 처음부터 다시 받는다.
  expect(
    await screen.findByRole("status", { name: "번역을 불러오는 중" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("재분석하지 못했습니다")).not.toBeInTheDocument();
  expect(screen.queryByText("그가 와 있다")).not.toBeInTheDocument();

  stream.push(previousEvent());

  expect(
    await screen.findByRole("status", { name: "재분석 중" }),
  ).toBeInTheDocument();
  expect(screen.getByText("그가 와 있다")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
