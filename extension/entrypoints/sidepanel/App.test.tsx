import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { requestAnalysis } from "@/utils/analysis-request";
import App from "./App";

function respondWith(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// 문장들을 분석 요청으로 넣는다. 드래그 범위는 문장 전체로 둔다.
function send(windowId: number, ...texts: string[]) {
  return requestAnalysis(
    windowId,
    texts.map((text) => ({ text, selection: { start: 0, end: text.length } })),
  );
}

// 문장마다 다른 응답을 준다. 정하지 않은 문장은 응답하지 않는다(분석 중으로 남는다).
function respondPerSentence(
  responses: Record<string, () => Promise<Response> | Response>,
) {
  const fetchMock = vi.fn((_url: string, init: RequestInit) => {
    const { text } = JSON.parse(init.body as string) as { text: string };
    const respond = responses[text];
    return respond
      ? Promise.resolve(respond())
      : new Promise<Response>(() => {});
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function analysis(translation: string) {
  return { translation_ko: translation, grammar: [], words: [] };
}

// 사이드 패널이 열린 창
let panelWindowId: number;

beforeEach(async () => {
  fakeBrowser.reset();
  const panelWindow = await fakeBrowser.windows.create({ focused: true });
  panelWindowId = panelWindow!.id!;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("사이드 패널에 앱 이름을 제목으로 보여준다", () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "Dragram" })).toBeInTheDocument();
});

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
  expect(JSON.parse(init.body)).toEqual({ text: "私は学生です。" });
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

function grammarItem(start: number, end: number, name: string) {
  return {
    start,
    end,
    name,
    explanation_ko: `${name} 설명`,
    review_status: "pending",
  };
}

test("문법 카드를 원문 순서대로 보이고, 카드마다 'AI 생성·미검수' 배지를 단다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    // 응답 순서와 상관없이 원문 순서대로 보인다.
    grammar: [grammarItem(4, 6, "정중 です"), grammarItem(1, 2, "주제 は")],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  const cards = await screen.findAllByRole("listitem");
  expect(
    cards.map((card) => within(card).getByRole("heading").textContent),
  ).toEqual(["주제 は", "정중 です"]);
  expect(within(cards[0]!).getByText("주제 は 설명")).toBeInTheDocument();
  for (const card of cards) {
    expect(within(card).getByText("AI 생성·미검수")).toBeInTheDocument();
  }
});

test("원문의 문법 구간에 형광펜을 칠하고, 카드 칩에 같은 구간 글자를 보인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は"), grammarItem(4, 6, "정중 です")],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  await screen.findAllByRole("listitem");
  const marks = document.querySelectorAll(".original mark");
  expect([...marks].map((mark) => mark.textContent)).toEqual(["は", "です"]);
  expect(document.querySelector(".original")!.textContent).toBe(
    "私は学生です。",
  );
  const chips = document.querySelectorAll(".grammar-chip");
  expect([...chips].map((chip) => chip.textContent)).toEqual(["は", "です"]);
  // 형광펜과 칩은 같은 색을 쓴다.
  expect(marks[0]!.className).toContain("highlight-0");
  expect(chips[0]!.className).toContain("highlight-0");
  expect(marks[1]!.className).toContain("highlight-1");
});

test("문법이 없으면 문법 칸 자리에 '문법 요소 없음'을 보인다", async () => {
  respondWith(200, { translation_ko: "도쿄", grammar: [], words: [] });
  render(<App />);

  await send(panelWindowId, "東京");

  expect(await screen.findByText("문법 요소 없음")).toBeInTheDocument();
});

function wordItem(start: number, end: number, lemma: string, reading: string) {
  return {
    start,
    end,
    lemma,
    reading,
    meaning_ko: `${lemma} 뜻`,
    review_status: "pending",
  };
}

test("탭에 문법과 단어 개수를 보이고, 처음에는 문법 탭을 보인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は"), grammarItem(4, 6, "정중 です")],
    words: [wordItem(2, 4, "学生", "がくせい")],
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  const tabs = await screen.findAllByRole("tab");
  expect(tabs.map((tab) => tab.textContent)).toEqual(["문법 2", "단어 1"]);
  expect(screen.getByRole("tab", { name: "문법 2" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("heading", { name: "주제 は" })).toBeInTheDocument();
  expect(screen.queryByText("学生 뜻")).not.toBeInTheDocument();
});

test("단어 탭에 단어마다 사전형, 읽기, 뜻과 'AI 생성·미검수' 배지를 원문 순서대로 보인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생으로서 먹고 있다.",
    grammar: [grammarItem(1, 2, "주제 は")],
    // 응답 순서와 상관없이 원문 순서대로 보인다.
    words: [wordItem(5, 7, "食べる", "たべる"), wordItem(0, 1, "私", "わたし")],
  });
  render(<App />);
  await send(panelWindowId, "私は学生で食べている");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));

  expect(screen.getByRole("tab", { name: "단어 2" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    screen.queryByRole("heading", { name: "주제 は" }),
  ).not.toBeInTheDocument();
  const rows = within(screen.getByRole("list", { name: "단어" })).getAllByRole(
    "listitem",
  );
  expect(
    rows.map((row) => within(row).getByRole("heading").textContent),
  ).toEqual(["私", "食べる"]);
  expect(within(rows[1]!).getByText("たべる")).toBeInTheDocument();
  expect(within(rows[1]!).getByText("食べる 뜻")).toBeInTheDocument();
  for (const row of rows) {
    expect(within(row).getByText("AI 생성·미검수")).toBeInTheDocument();
  }
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

test("서버에는 문장 분석 요청을 동시에 3개까지만 보내고, 끝나는 대로 다음 문장을 보낸다", async () => {
  let finishFirst: (response: Response) => void = () => {};
  const fetchMock = respondPerSentence({
    "一。": () => new Promise<Response>((resolve) => (finishFirst = resolve)),
  });
  render(<App />);

  await send(panelWindowId, "一。", "二。", "三。", "四。", "五。");

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  finishFirst(json(200, analysis("하나.")));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
});
