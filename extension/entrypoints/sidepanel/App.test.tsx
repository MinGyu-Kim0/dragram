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

function respondWith(status: number, body: object) {
  // 응답 본문은 한 번만 읽을 수 있어 요청마다 새로 만든다.
  const fetchMock = vi.fn((_url: string, _init: RequestInit) =>
    Promise.resolve(json(status, body)),
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

interface AnalysisBody {
  translation_ko: string;
  grammar: unknown[];
  words: unknown[];
  ruby?: unknown[];
}

// 성공 응답은 서버처럼 줄 단위 JSON 이벤트 두 줄(번역 → 문법·단어)로 한 번에 준다.
// 테스트가 정하지 않은 루비는 빈 목록으로 채운다. 실패 응답은 JSON 본문 그대로다.
function json(status: number, body: object) {
  if (status !== 200) {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }
  const { ruby = [], ...result } = body as AnalysisBody;
  return ndjson([
    { type: "translation", translation_ko: result.translation_ko, ruby },
    { type: "analysis", ...result },
  ]);
}

function ndjson(events: object[]) {
  return new Response(
    events.map((event) => JSON.stringify(event) + "\n").join(""),
    {
      status: 200,
      headers: { "Content-Type": "application/x-ndjson" },
    },
  );
}

// 이벤트를 테스트가 정한 때에 한 줄씩 흘려보내는 응답
function streamed() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  const encoder = new TextEncoder();
  return {
    response: new Response(body, {
      status: 200,
      headers: { "Content-Type": "application/x-ndjson" },
    }),
    push(event: object) {
      controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
    },
    end() {
      controller.close();
    },
  };
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

// 문장 하나를 드래그 범위와 함께 분석 요청으로 넣는다.
function sendSelected(
  windowId: number,
  text: string,
  start: number,
  end: number,
) {
  return requestAnalysis(windowId, [{ text, selection: { start, end } }]);
}

// 원문에서 드래그 핸들 자리를 [ ]로 바꿔 읽는다.
function originalWithHandles(): string {
  const original = document
    .querySelector(".original")!
    .cloneNode(true) as Element;
  original.querySelectorAll("rt").forEach((rt) => rt.remove());
  original
    .querySelectorAll(".drag-handle-start")
    .forEach((handle) => handle.replaceWith("["));
  original
    .querySelectorAll(".drag-handle-end")
    .forEach((handle) => handle.replaceWith("]"));
  return original.textContent!;
}

test("원문에 실제로 드래그한 범위의 시작과 끝에 핸들을 붙인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は"), grammarItem(4, 6, "정중 です")],
    words: [],
  });
  render(<App />);

  // 学生で까지 고르지 않고 は学生만 골랐다.
  await sendSelected(panelWindowId, "私は学生です。", 1, 4);

  await screen.findAllByRole("listitem");
  expect(originalWithHandles()).toBe("私[は学生]です。");
  // 핸들은 글자가 아니다.
  expect(document.querySelector(".original")!.textContent).toBe(
    "私は学生です。",
  );
});

test("드래그 범위가 문법 구간 안에서 시작·끝나도 형광펜을 쪼개지 않는다", async () => {
  respondWith(200, {
    translation_ko: "학생입니다.",
    grammar: [grammarItem(0, 2, "명사 学生"), grammarItem(2, 4, "정중 です")],
    words: [],
  });
  render(<App />);

  // 生で만 골랐다. 두 형광펜 모두 안에서 경계가 생긴다.
  await sendSelected(panelWindowId, "学生です。", 1, 3);

  await screen.findAllByRole("listitem");
  const marks = document.querySelectorAll(".original mark");
  expect([...marks].map((mark) => mark.textContent)).toEqual(["学生", "です"]);
  expect(originalWithHandles()).toBe("学[生で]す。");
});

test("응답 전에도 원문에 드래그 범위를 표시한다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
  render(<App />);

  await sendSelected(panelWindowId, "私は学生です。", 2, 4);

  await screen.findByRole("status", { name: "번역을 불러오는 중" });
  expect(originalWithHandles()).toBe("私は[学生]です。");
});

test("원문 카드의 버튼으로 드래그 핸들을 끄고 다시 켤 수 있다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
  render(<App />);
  await sendSelected(panelWindowId, "私は学生です。", 2, 4);
  const toggle = await screen.findByRole("button", { name: "드래그 표시" });
  expect(toggle).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(toggle);

  expect(toggle).toHaveAttribute("aria-pressed", "false");
  expect(originalWithHandles()).toBe("私は学生です。");

  fireEvent.click(toggle);

  expect(originalWithHandles()).toBe("私は[学生]です。");
});

test("끈 드래그 핸들은 패널을 다시 열어도 꺼져 있다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
  const { unmount } = render(<App />);
  await sendSelected(panelWindowId, "私は学生です。", 2, 4);
  fireEvent.click(await screen.findByRole("button", { name: "드래그 표시" }));
  unmount();

  render(<App />);
  await sendSelected(panelWindowId, "私は学生です。", 2, 4);

  const toggle = await screen.findByRole("button", { name: "드래그 표시" });
  await waitFor(() => expect(toggle).toHaveAttribute("aria-pressed", "false"));
  expect(originalWithHandles()).toBe("私は学生です。");
});

test("드래그 핸들을 꺼도 드래그한 부분의 카드 표시는 그대로다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は"), grammarItem(4, 6, "정중 です")],
    words: [],
  });
  render(<App />);
  await sendSelected(panelWindowId, "私は学生です。", 4, 6);

  fireEvent.click(await screen.findByRole("button", { name: "드래그 표시" }));

  const cards = await screen.findAllByRole("listitem");
  expect(within(cards[0]!).getByText("드래그한 부분")).toBeInTheDocument();
});

test("드래그 범위와 겹친 문법 카드를 먼저 보이고 '드래그한 부분'을 붙인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [
      grammarItem(0, 1, "1인칭 私"),
      grammarItem(1, 2, "주제 は"),
      grammarItem(4, 6, "정중 です"),
    ],
    words: [],
  });
  render(<App />);

  // 学生です만 골랐다. 정중 です만 겹친다.
  await sendSelected(panelWindowId, "私は学生です。", 2, 6);

  const cards = await screen.findAllByRole("listitem");
  expect(
    cards.map((card) => within(card).getByRole("heading").textContent),
  ).toEqual(["정중 です", "1인칭 私", "주제 は"]);
  expect(within(cards[0]!).getByText("드래그한 부분")).toBeInTheDocument();
  expect(cards[0]!.className).toContain("dragged");
  for (const card of cards.slice(1)) {
    expect(within(card).queryByText("드래그한 부분")).not.toBeInTheDocument();
    expect(card.className).not.toContain("dragged");
  }
  // 카드 순서가 바뀌어도 칩 색은 원문의 형광펜 색과 같다.
  expect(within(cards[0]!).getByText("です").className).toContain(
    "highlight-2",
  );
});

test("드래그 범위의 끝에 닿기만 하는 문법 카드는 겹친 것으로 보지 않는다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は"), grammarItem(4, 6, "정중 です")],
    words: [],
  });
  render(<App />);

  await sendSelected(panelWindowId, "私は学生です。", 2, 4);

  const cards = await screen.findAllByRole("listitem");
  expect(screen.queryByText("드래그한 부분")).not.toBeInTheDocument();
  expect(
    cards.map((card) => within(card).getByRole("heading").textContent),
  ).toEqual(["주제 は", "정중 です"]);
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

test("단어 탭에서도 드래그 범위와 겹친 단어를 먼저 보이고 '드래그한 부분'을 붙인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생으로서 먹고 있다.",
    grammar: [],
    words: [
      wordItem(0, 1, "私", "わたし"),
      wordItem(2, 4, "学生", "がくせい"),
      wordItem(5, 7, "食べる", "たべる"),
    ],
  });
  render(<App />);
  // 生で食만 골랐다. 学生과 食べる가 겹친다.
  await sendSelected(panelWindowId, "私は学生で食べている", 3, 6);

  fireEvent.click(await screen.findByRole("tab", { name: "단어 3" }));

  const rows = within(screen.getByRole("list", { name: "단어" })).getAllByRole(
    "listitem",
  );
  expect(
    rows.map((row) => within(row).getByRole("heading").textContent),
  ).toEqual(["学生", "食べる", "私"]);
  for (const row of rows.slice(0, 2)) {
    expect(within(row).getByText("드래그한 부분")).toBeInTheDocument();
    expect(row.className).toContain("dragged");
  }
  expect(within(rows[2]!).queryByText("드래그한 부분")).not.toBeInTheDocument();
  expect(rows[2]!.className).not.toContain("dragged");
});

function rubyItem(start: number, end: number, reading: string) {
  return { start, end, reading };
}

// 원문에 달린 루비를 [밑글자, 읽기]로 읽는다.
function rubies(): [string, string][] {
  return [...document.querySelectorAll(".original ruby")].map((ruby) => {
    const rt = ruby.querySelector("rt")!.textContent!;
    return [ruby.textContent!.slice(0, -rt.length), rt];
  });
}

test("원문 한자 위에 루비를 기본으로 보인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(2, 4, "명사 学生")],
    words: [],
    ruby: [rubyItem(0, 1, "わたし"), rubyItem(2, 4, "がくせい")],
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  await screen.findByText("나는 학생입니다.");
  expect(rubies()).toEqual([
    ["私", "わたし"],
    ["学生", "がくせい"],
  ]);
  expect(screen.getByRole("button", { name: "루비" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // 형광펜 안에도 루비를 단다.
  expect(document.querySelector(".original mark ruby")).not.toBeNull();
});

test("루비 버튼을 끄면 루비가 사라지고, 끈 값은 패널을 다시 열어도 유지된다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [],
    words: [],
    ruby: [rubyItem(0, 1, "わたし")],
  });
  const { unmount } = render(<App />);
  await send(panelWindowId, "私は学生です。");
  await screen.findByText("나는 학생입니다.");

  fireEvent.click(screen.getByRole("button", { name: "루비" }));

  expect(rubies()).toEqual([]);
  expect(document.querySelector(".original")!.textContent).toBe(
    "私は学生です。",
  );

  unmount();
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [],
    words: [],
    ruby: [rubyItem(0, 1, "わたし")],
  });
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  await screen.findByText("나는 학생입니다.");
  await waitFor(() => expect(rubies()).toEqual([]));
});

test("드래그 핸들이 루비 단어 안에 걸리면 단어 바깥에 붙인다", async () => {
  respondWith(200, {
    translation_ko: "중간선거까지",
    grammar: [],
    words: [],
    ruby: [rubyItem(0, 2, "ちゅうかん"), rubyItem(2, 4, "せんきょ")],
  });
  render(<App />);

  // 間選만 골랐다. 시작은 中間 안, 끝은 選挙 안이다.
  await sendSelected(panelWindowId, "中間選挙まで", 1, 3);

  await screen.findByText("중간선거까지");
  expect(rubies()).toEqual([
    ["中間", "ちゅうかん"],
    ["選挙", "せんきょ"],
  ]);
  expect(originalWithHandles()).toBe("[中間選挙]まで");
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
  expect(
    screen.getByRole("status", { name: "문법·단어를 불러오는 중" }),
  ).toBeInTheDocument();
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
    screen.queryByRole("status", { name: "문법·단어를 불러오는 중" }),
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

function approvedGrammarItem(start: number, end: number, name: string) {
  return { ...grammarItem(start, end, name), review_status: "approved" };
}

test("LLM 없이 확정한 문법은 번역보다 먼저 보이고, 분석이 끝나면 전체로 바뀐다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "彼が来ている");

  stream.push({
    type: "grammar",
    grammar: [approvedGrammarItem(3, 6, "진행")],
  });

  const [card] = await screen.findAllByRole("listitem");
  expect(within(card!).getByRole("heading").textContent).toBe("진행");
  expect(within(card!).queryByText("AI 생성·미검수")).not.toBeInTheDocument();
  expect(
    [...document.querySelectorAll(".original mark")].map((m) => m.textContent),
  ).toEqual(["ている"]);
  // 번역은 아직 불러오는 중이다.
  expect(
    screen.getByRole("status", { name: "번역을 불러오는 중" }),
  ).toBeInTheDocument();

  stream.push({
    type: "translation",
    translation_ko: "그가 와 있다",
    ruby: [],
  });
  stream.push({
    type: "analysis",
    translation_ko: "그가 와 있다",
    grammar: [grammarItem(1, 2, "주격 が"), approvedGrammarItem(3, 6, "진행")],
    words: [],
  });
  stream.end();

  expect(
    await screen.findByRole("tab", { name: "문법 2" }),
  ).toBeInTheDocument();
  expect(
    screen
      .getAllByRole("listitem")
      .map((item) => within(item).getByRole("heading").textContent),
  ).toEqual(["주격 が", "진행"]);
});

test("확정한 문법을 보인 뒤 실패하면 그 문법은 남기고 실패를 보인다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        ndjson([
          { type: "grammar", grammar: [approvedGrammarItem(3, 6, "진행")] },
          { type: "error", error: "ANALYSIS:FAILED" },
        ]),
      ),
    ),
  );
  render(<App />);

  await send(panelWindowId, "彼が来ている");

  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();
  const [card] = screen.getAllByRole("listitem");
  expect(within(card!).getByRole("heading").textContent).toBe("진행");
});

// 후보가 모두 검수된 판별 대상 구간
function checkingItem(start: number, end: number, ...names: string[]) {
  return {
    start,
    end,
    candidates: names.map((name) => ({ name, review_status: "approved" })),
  };
}

test("판별을 기다리는 구간은 '확인 중' 점선 카드와 점선 밑줄로 먼저 보이고, 분석이 오면 고른 용법으로 바뀐다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "彼が来ている");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [checkingItem(3, 6, "진행", "결과 상태")],
  });

  const [card] = await screen.findAllByRole("listitem");
  expect(card).toHaveClass("checking");
  expect(within(card!).getByRole("heading").textContent).toBe(
    "진행 · 결과 상태",
  );
  expect(within(card!).getByText("확인 중")).toBeInTheDocument();
  expect(within(card!).queryByText("AI 생성·미검수")).not.toBeInTheDocument();
  expect(
    [...document.querySelectorAll(".original mark.checking")].map(
      (mark) => mark.textContent,
    ),
  ).toEqual(["ている"]);
  expect(document.querySelectorAll(".original mark.highlight")).toHaveLength(0);

  stream.push({
    type: "translation",
    translation_ko: "그가 와 있다",
    ruby: [],
  });
  stream.push({
    type: "analysis",
    translation_ko: "그가 와 있다",
    grammar: [grammarItem(3, 6, "진행")],
    words: [],
  });
  stream.end();

  expect(
    await screen.findByRole("tab", { name: "문법 1" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("확인 중")).not.toBeInTheDocument();
  expect(document.querySelectorAll(".original mark.checking")).toHaveLength(0);
  expect(
    [...document.querySelectorAll(".original mark.highlight")].map(
      (mark) => mark.textContent,
    ),
  ).toEqual(["ている"]);
});

test("확정 문법과 확인 중 구간을 원문 순서대로 함께 보인다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "歩きながら来ている");

  stream.push({
    type: "grammar",
    grammar: [approvedGrammarItem(6, 9, "진행")],
    checking: [checkingItem(2, 5, "동시 동작")],
  });

  await screen.findAllByRole("listitem");
  expect(
    screen
      .getAllByRole("listitem")
      .map((item) => within(item).getByRole("heading").textContent),
  ).toEqual(["동시 동작", "진행"]);
});

test("확인 중 구간을 보인 뒤 실패하면 확인 중은 지우고 확정 문법만 남긴다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        ndjson([
          {
            type: "grammar",
            grammar: [approvedGrammarItem(6, 9, "진행")],
            checking: [checkingItem(2, 5, "동시 동작")],
          },
          { type: "error", error: "ANALYSIS:FAILED" },
        ]),
      ),
    ),
  );
  render(<App />);

  await send(panelWindowId, "歩きながら来ている");

  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();
  expect(
    screen
      .getAllByRole("listitem")
      .map((item) => within(item).getByRole("heading").textContent),
  ).toEqual(["진행"]);
  expect(screen.queryByText("확인 중")).not.toBeInTheDocument();
  expect(document.querySelectorAll(".original mark.checking")).toHaveLength(0);
});

test("확인 중 구간의 경계가 확정 문법 안에 있어도 그 형광펜을 쪼개지 않는다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "彼が来ている");

  stream.push({
    type: "grammar",
    grammar: [approvedGrammarItem(3, 6, "진행")],
    checking: [checkingItem(5, 6, "보조 동사")],
  });

  await screen.findAllByRole("listitem");
  expect(
    [...document.querySelectorAll(".original mark")].map((m) => m.textContent),
  ).toEqual(["ている"]);
});

test("확인 중 카드는 번역이 와도 남고, 해당 없음으로 판정되면 사라지며, 드래그 범위와 겹치면 먼저 보인다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  // 드래그 범위: 来ている(2~6)
  await sendSelected(panelWindowId, "彼が来ている", 2, 6);

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [checkingItem(1, 2, "주격"), checkingItem(3, 6, "진행")],
  });
  stream.push({
    type: "translation",
    translation_ko: "그가 와 있다",
    ruby: [],
  });

  expect(await screen.findByText("그가 와 있다")).toBeInTheDocument();
  expect(
    screen
      .getAllByRole("listitem")
      .map((item) => within(item).getByRole("heading").textContent),
  ).toEqual(["진행", "주격"]);

  // が는 해당 없음, ている는 진행
  stream.push({
    type: "analysis",
    translation_ko: "그가 와 있다",
    grammar: [grammarItem(3, 6, "진행")],
    words: [],
  });
  stream.end();

  expect(
    await screen.findByRole("tab", { name: "문법 1" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("주격")).not.toBeInTheDocument();
});

test("확인 중 카드의 후보에 미검수 용법이 있으면 'AI 생성·미검수' 배지를 단다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "彼が来ている");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [
      {
        start: 3,
        end: 6,
        candidates: [
          { name: "진행", review_status: "approved" },
          { name: "결과 상태", review_status: "pending" },
        ],
      },
    ],
  });

  const [card] = await screen.findAllByRole("listitem");
  expect(within(card!).getByText("확인 중")).toBeInTheDocument();
  expect(within(card!).getByText("AI 생성·미검수")).toBeInTheDocument();
});
