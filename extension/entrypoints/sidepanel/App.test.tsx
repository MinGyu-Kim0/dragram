import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { requestAnalysis } from "@/utils/analysis-request";
import { loadToken, saveToken, signOut } from "@/utils/auth";
import { handleExternalMessage, WEB_ORIGIN } from "@/utils/external-messages";
import { fetchNames, removeName, saveName } from "@/utils/names";
import App from "./App";

// 지정한 이름 API(#136)는 분석 요청의 fetch 가짜와 섞이지 않게 따로 가짜로 둔다.
vi.mock("@/utils/names", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/names")>()),
  fetchNames: vi.fn(),
  saveName: vi.fn(),
  removeName: vi.fn(),
}));

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
  // 웹에서 연결한 상태로 시작한다(#109).
  await saveToken("extension-token");
  vi.mocked(fetchNames).mockReset().mockResolvedValue([]);
  vi.mocked(saveName).mockReset();
  vi.mocked(removeName).mockReset();
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
    state: "decided",
    name,
    explanation_ko: `${name} 설명`,
    korean_equivalent: null,
    korean_equivalent_review_status: null,
    pos_tags: [],
    function_tags: [],
    function_tags_review_status: null,
    review_status: "pending",
    register: "standard",
    variant_of: null,
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

// 사전 단어. sense를 null로 주면 뜻을 준비하는 중인 단어다. 영어 뜻은 `${표제} gloss`, 한국어 뜻은
// 검수된 `${표제} 뜻`이다.
function wordItem(
  start: number,
  end: number,
  form: string,
  reading: string,
  sense: object | null = {},
  tags: string[] = ["noun"],
) {
  return {
    start,
    end,
    dictionary_form: form,
    reading,
    tags,
    in_dictionary: true,
    sense: sense && {
      tags: [],
      gloss_en: [`${form} gloss`],
      origin: "jmdict",
      status: "approved",
      meaning_ko: `${form} 뜻`,
      meaning_status: "reviewed",
      ...sense,
    },
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

test("단어 탭에 단어마다 사전형, 읽기, 태그, 한국어 뜻을 원문 순서대로 보이고 JMdict 출처를 단다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생으로서 먹고 있다.",
    grammar: [grammarItem(1, 2, "주제 は")],
    // 응답 순서와 상관없이 원문 순서대로 보인다.
    words: [
      wordItem(
        5,
        7,
        "食べる",
        "たべる",
        { tags: ["transitive"], gloss_en: ["to eat", "to live on"] },
        ["verb", "group2"],
      ),
      wordItem(0, 1, "私", "わたし", {}, ["pronoun"]),
    ],
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
  const words = rows.filter((row) => row.classList.contains("word-row"));
  expect(
    words.map((row) => within(row).getByRole("heading").textContent),
  ).toEqual(["私", "食べる"]);
  expect(within(words[1]!).getByText("たべる")).toBeInTheDocument();
  expect(within(words[1]!).getByText("食べる 뜻")).toBeInTheDocument();
  // 영어 뜻은 보이지 않는다(LLM 입력과 admin에만 쓴다).
  expect(screen.queryByText(/to eat/)).not.toBeInTheDocument();
  // 단어 전체 태그 뒤에 고른 뜻의 태그를 보인다.
  expect(
    within(within(words[1]!).getByRole("list", { name: "태그" }))
      .getAllByRole("listitem")
      .map((tag) => tag.textContent),
  ).toEqual(["동사", "2그룹", "타동사"]);
  // 검수된 JMdict 뜻에는 배지가 없고 출처 각주가 있다.
  for (const row of words) {
    expect(within(row).queryByText("AI 생성·미검수")).not.toBeInTheDocument();
    expect(within(row).queryByText("AI 번역")).not.toBeInTheDocument();
  }
  expect(screen.getByRole("link", { name: "JMdict" })).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "CC BY-SA 4.0" }),
  ).toBeInTheDocument();
});

test("뜻의 출처·검수 상태에 따라 'AI 생성·미검수'와 'AI 번역' 배지를 단다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [],
    words: [
      wordItem(0, 1, "一", "いち", { origin: "llm", status: "pending" }),
      wordItem(1, 2, "二", "に", { meaning_ko: "둘", meaning_status: "ai" }),
      wordItem(2, 3, "三", "さん", {
        meaning_ko: "셋",
        meaning_status: "reviewed",
      }),
    ],
  });
  render(<App />);
  await send(panelWindowId, "一二三");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 3" }));

  const [llm, translated, reviewed] = within(
    screen.getByRole("list", { name: "단어" }),
  )
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
  expect(within(llm!).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(within(translated!).getByText("둘")).toBeInTheDocument();
  expect(within(translated!).getByText("AI 번역")).toBeInTheDocument();
  expect(within(reviewed!).getByText("셋")).toBeInTheDocument();
  expect(within(reviewed!).queryByText("AI 번역")).not.toBeInTheDocument();
});

test("관리자가 승인한 LLM 뜻에는 'AI 생성·미검수'도 'AI 번역'도 달지 않는다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [],
    words: [
      wordItem(0, 1, "一", "いち", {
        origin: "llm",
        status: "approved",
        meaning_ko: "하나",
        meaning_status: "ai",
      }),
    ],
  });
  render(<App />);
  await send(panelWindowId, "一");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 1" }));

  expect(screen.getByText("하나")).toBeInTheDocument();
  expect(screen.queryByText("AI 생성·미검수")).not.toBeInTheDocument();
  expect(screen.queryByText("AI 번역")).not.toBeInTheDocument();
});

test("LLM보다 먼저 온 단어는 탭에 바로 보이고, 뜻을 준비하는 중인 단어는 분석이 오면 채운다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "学生が開いた");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [],
    words: [
      wordItem(0, 2, "学生", "がくせい"),
      wordItem(3, 5, "開く", "ひらく", null, ["verb", "group1"]),
    ],
  });

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));
  expect(
    screen.getByRole("status", { name: "번역을 불러오는 중" }),
  ).toBeInTheDocument();
  expect(screen.getByText("学生 뜻")).toBeInTheDocument();
  expect(
    screen.getByRole("status", { name: "뜻을 준비하는 중" }),
  ).toBeInTheDocument();
  // 문법은 아직 오지 않아 '문법 요소 없음'이라고 단정하지 않는다.
  fireEvent.click(screen.getByRole("tab", { name: "문법 0" }));
  expect(
    screen.getByRole("status", { name: "문법을 불러오는 중" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("문법 요소 없음")).not.toBeInTheDocument();

  stream.push({
    type: "translation",
    translation_ko: "학생이 열었다",
    ruby: [],
  });
  stream.push({
    type: "analysis",
    translation_ko: "학생이 열었다",
    grammar: [],
    words: [
      wordItem(0, 2, "学生", "がくせい"),
      wordItem(3, 5, "開く", "ひらく", { meaning_ko: "열다" }),
    ],
  });
  stream.end();

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));
  expect(await screen.findByText("열다")).toBeInTheDocument();
  expect(
    screen.queryByRole("status", { name: "뜻을 준비하는 중" }),
  ).not.toBeInTheDocument();
});

test("한국어 뜻이 아직 없으면 준비 중, 만들지 못했으면 실패 문구를 보인다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [],
    words: [
      wordItem(0, 1, "一", "いち", { meaning_ko: null, meaning_status: "ai" }),
      wordItem(1, 2, "二", "に", {
        meaning_ko: null,
        meaning_status: "failed",
      }),
    ],
  });
  render(<App />);
  await send(panelWindowId, "一二");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));

  const [waiting, failed] = within(screen.getByRole("list", { name: "단어" }))
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
  expect(
    within(waiting!).getByRole("status", { name: "뜻을 준비하는 중" }),
  ).toBeInTheDocument();
  expect(
    within(failed!).getByText("뜻을 만들지 못했습니다"),
  ).toBeInTheDocument();
  // 단어 하나의 뜻 실패는 문장 실패가 아니다(표제·읽기·각주는 그대로).
  expect(within(failed!).getByText("に")).toBeInTheDocument();
  expect(screen.queryByText(/gloss/)).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "JMdict" })).toBeInTheDocument();
});

test("LLM이 만든 단어만 있으면 JMdict 출처 각주를 달지 않는다", async () => {
  respondWith(200, {
    translation_ko: "달리고 있다",
    grammar: [],
    words: [
      {
        ...wordItem(0, 2, "走る", "はしる", {
          origin: "llm",
          status: "pending",
          meaning_ko: "달리다",
        }),
        in_dictionary: false,
      },
    ],
  });
  render(<App />);
  await send(panelWindowId, "走っている");

  fireEvent.click(await screen.findByRole("tab", { name: "단어 1" }));

  expect(screen.getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "JMdict" }),
  ).not.toBeInTheDocument();
});

test("분석 전에 온 judged 이벤트로 고른 뜻을 채운다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "本を開いた");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [],
    words: [wordItem(2, 4, "開く", "ひらく", null)],
  });
  stream.push({ type: "translation", translation_ko: "책을 펼쳤다", ruby: [] });
  stream.push({
    type: "judged",
    grammar: [],
    checking: [],
    words: [
      wordItem(2, 4, "開く", "ひらく", {
        meaning_ko: null,
        meaning_status: "ai",
      }),
    ],
  });

  fireEvent.click(await screen.findByRole("tab", { name: "단어 1" }));
  expect(screen.getByText("책을 펼쳤다")).toBeInTheDocument();
  expect(
    screen.getByRole("status", { name: "뜻을 준비하는 중" }),
  ).toBeInTheDocument();

  stream.push({
    type: "judged",
    grammar: [],
    checking: [],
    words: [
      wordItem(2, 4, "開く", "ひらく", {
        meaning_ko: "피다",
        meaning_status: "ai",
      }),
    ],
  });

  expect(await screen.findByText("피다")).toBeInTheDocument();
  expect(screen.getByText("AI 번역")).toBeInTheDocument();
  expect(screen.getByText("책을 펼쳤다")).toBeInTheDocument();
  stream.end();
});

test("먼저 온 단어가 있어도 분석이 실패하면 단어를 지우고 실패를 보인다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        ndjson([
          {
            type: "grammar",
            grammar: [],
            checking: [],
            words: [wordItem(3, 5, "開く", "ひらく", null)],
          },
          { type: "translation", translation_ko: "학생이 열었다", ruby: [] },
          { type: "error", error: "ANALYSIS:FAILED" },
        ]),
      ),
    ),
  );
  render(<App />);

  await send(panelWindowId, "学生が開いた");

  expect(
    await screen.findByText("문법·단어를 분석하지 못했습니다"),
  ).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("status", { name: "뜻을 준비하는 중" }),
  ).not.toBeInTheDocument();
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

  const rows = within(screen.getByRole("list", { name: "단어" }))
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
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

test("첫 LLM 응답이 판정한 문법은 분석 전에 카드로 보이고, 번역도 그대로 남는다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "彼が来ている");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [checkingItem(3, 6, "진행", "결과 상태")],
  });
  stream.push({
    type: "translation",
    translation_ko: "그가 와 있다",
    ruby: [],
  });
  stream.push({
    type: "judged",
    grammar: [grammarItem(3, 6, "결과 상태")],
    checking: [],
    words: [],
  });

  expect(
    await screen.findByRole("heading", { name: "결과 상태" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("확인 중")).not.toBeInTheDocument();
  expect(
    within(cardOf("결과 상태")).getByText("AI 생성·미검수"),
  ).toBeInTheDocument();
  expect(screen.getByText("그가 와 있다")).toBeInTheDocument();
  stream.end();
});

test("판정한 문법을 받은 뒤 실패하면 LLM 없이 확정한 문법만 남긴다", async () => {
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
          {
            type: "translation",
            translation_ko: "걸으면서 오고 있다",
            ruby: [],
          },
          {
            type: "judged",
            grammar: [
              grammarItem(2, 5, "동시 동작"),
              approvedGrammarItem(6, 9, "진행"),
            ],
            checking: [],
            words: [],
          },
          { type: "error", error: "ANALYSIS:FAILED" },
        ]),
      ),
    ),
  );
  render(<App />);

  await send(panelWindowId, "歩きながら来ている");

  // 판정은 저장되지 않았으므로 보이지 않는다.
  expect(
    await screen.findByText("문법·단어를 분석하지 못했습니다"),
  ).toBeInTheDocument();
  expect(
    screen
      .getAllByRole("listitem")
      .map((item) => within(item).getByRole("heading").textContent),
  ).toEqual(["진행"]);
});

function cardOf(name: string) {
  return screen.getByRole("heading", { name }).closest("li")!;
}

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
    screen.queryByRole("status", { name: "문법·단어를 불러오는 중" }),
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

const failed = () => json(502, { error: "ANALYSIS:FAILED" });

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

// 해석 갈림 구간: 주 용법(진행)과 대안
function divergentItem(...alternatives: object[]) {
  return { ...grammarItem(3, 6, "진행"), state: "divergent", alternatives };
}

function alternativeItem(
  name: string,
  translation: string,
  status = "pending",
) {
  return {
    name,
    korean_equivalent: null,
    korean_equivalent_review_status: null,
    function_tags: [],
    function_tags_review_status: null,
    translation_ko: translation,
    review_status: status,
  };
}

test("해석 갈림 구간은 점선 카드 아래에 '다른 해석: 대안 — 대안 번역' 줄을 대안마다 보이고, 미검수 대안에 배지를 단다", async () => {
  respondWith(200, {
    translation_ko: "그가 와 있다",
    grammar: [
      divergentItem(
        alternativeItem("결과 상태", "그가 와 있는 상태다"),
        alternativeItem("완료", "그가 와 버렸다", "approved"),
      ),
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "彼が来ている");

  const [card] = await screen.findAllByRole("listitem");
  expect(card).toHaveClass("divergent");
  expect(within(card!).getByRole("heading").textContent).toBe("진행");
  const lines = within(card!).getAllByText(/^다른 해석:/);
  expect(lines.map((line) => line.textContent)).toEqual([
    "다른 해석: 결과 상태 — 그가 와 있는 상태다",
    "다른 해석: 완료 — 그가 와 버렸다",
  ]);
  // 주 용법 배지 하나와 미검수 대안 배지 하나
  expect(within(card!).getAllByText("AI 생성·미검수")).toHaveLength(2);
  expect(
    within(lines[0]!.closest("li.alternative")!).getByText("AI 생성·미검수"),
  ).toBeInTheDocument();
  expect(
    within(lines[1]!.closest("li.alternative")!).queryByText("AI 생성·미검수"),
  ).not.toBeInTheDocument();
});

test("대안이 모두 빠진 해석 갈림 구간은 점선 없는 보통 카드로 보인다", async () => {
  respondWith(200, {
    translation_ko: "그가 와 있다",
    grammar: [divergentItem()],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "彼が来ている");

  const [card] = await screen.findAllByRole("listitem");
  expect(card).not.toHaveClass("divergent");
  expect(within(card!).queryByText(/^다른 해석:/)).not.toBeInTheDocument();
});

test("미확정 구간은 패턴 이름과 '판단하지 못함'으로 보이고 문법 개수에 들어간다", async () => {
  respondWith(200, {
    translation_ko: "그가 와 있다",
    grammar: [
      grammarItem(1, 2, "주격 が"),
      {
        start: 3,
        end: 6,
        state: "unresolved",
        name: "ている",
        explanation_ko: null,
        korean_equivalent: null,
        korean_equivalent_review_status: null,
        pos_tags: [],
        function_tags: [],
        function_tags_review_status: null,
        review_status: "pending",
        register: "standard",
        variant_of: null,
      },
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "彼が来ている");

  expect(
    await screen.findByRole("tab", { name: "문법 2" }),
  ).toBeInTheDocument();
  const card = screen.getAllByRole("listitem")[1]!;
  expect(card).not.toHaveClass("divergent");
  expect(within(card).getByRole("heading").textContent).toBe("ている");
  expect(within(card).getByText("판단하지 못함")).toHaveClass(
    "unresolved-note",
  );
  expect(within(card).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(
    [...document.querySelectorAll(".original mark.highlight")].map(
      (mark) => mark.textContent,
    ),
  ).toEqual(["が", "ている"]);
});

test("확인 중 카드는 분석이 오면 해석 갈림 카드로 바뀌고, 번역도 분석의 번역으로 바뀐다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "彼が来ている");

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [checkingItem(3, 6, "진행", "결과 상태")],
  });
  stream.push({
    type: "translation",
    translation_ko: "그가 와 있다",
    ruby: [],
  });
  expect(await screen.findByText("확인 중")).toBeInTheDocument();

  stream.push({
    type: "analysis",
    translation_ko: "그가 와 있는 상태다",
    grammar: [
      {
        ...grammarItem(3, 6, "결과 상태"),
        state: "divergent",
        alternatives: [alternativeItem("진행", "그가 오고 있다")],
      },
    ],
    words: [],
  });
  stream.end();

  expect(
    await screen.findByRole("tab", { name: "문법 1" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("확인 중")).not.toBeInTheDocument();
  expect(screen.getByText("그가 와 있는 상태다")).toBeInTheDocument();
  expect(screen.queryByText("그가 와 있다")).not.toBeInTheDocument();
  const [card] = screen
    .getAllByRole("listitem")
    .filter((li) => li.classList.contains("grammar-card"));
  expect(card).toHaveClass("divergent");
});

test("회화체 구간은 '회화체' 배지를 달고, 원형에 연결됐으면 제목 아래에 원형 안내 한 줄을 둔다", async () => {
  respondWith(200, {
    translation_ko: "다 먹어 버렸다",
    grammar: [
      {
        ...grammarItem(2, 5, "완료"),
        register: "colloquial",
        variant_of: "てしまう",
      },
      // 연결을 푼 회화체는 배지만 남는다.
      { ...grammarItem(5, 6, "과거"), register: "colloquial" },
      grammarItem(0, 2, "명사"),
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "全部食べちゃった");

  await screen.findByRole("tab", { name: "문법 3" });
  const [standard, linked, unlinked] = screen.getAllByRole("listitem");
  expect(within(linked!).getByText("회화체")).toHaveClass("badge-neutral");
  expect(within(linked!).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(within(linked!).getByText("「てしまう」의 회화체")).toHaveClass(
    "variant-note",
  );
  expect(within(unlinked!).getByText("회화체")).toBeInTheDocument();
  expect(unlinked!.querySelector(".variant-note")).toBeNull();
  expect(within(standard!).queryByText("회화체")).toBeNull();
});

// 구성 문법(#65): 긴 문법 안에 완전히 들어가는 문법은 서버가 그 항목의 parts로 보낸다.
// 문장: 食べてしまった (食べ 0-2 / て 2-3 / しまっ 3-6 / た 6-7)
function withParts(item: object, ...parts: object[]) {
  return { ...item, parts };
}

function grammarCards() {
  return screen
    .getAllByRole("listitem")
    .filter((li) => li.classList.contains("grammar-card"));
}

function cardHeading(card: HTMLElement) {
  return within(card).getByRole("heading", { level: 3 }).textContent;
}

test("구성 문법은 바깥 카드 안의 하위 박스로 보이고, 글자와 칩은 바깥 카드 색을 쓴다", async () => {
  respondWith(200, {
    translation_ko: "먹어 버렸다",
    grammar: [
      withParts(grammarItem(2, 6, "완료"), grammarItem(2, 3, "연결")),
      grammarItem(6, 7, "과거"),
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "食べてしまった");

  // 하위 박스도 문법 개수에 센다.
  await screen.findByRole("tab", { name: "문법 3" });
  const [outer, past] = grammarCards();
  expect(grammarCards().map(cardHeading)).toEqual(["완료", "과거"]);
  const [part] = within(
    within(outer!).getByRole("list", { name: "구성 문법" }),
  ).getAllByRole("listitem");
  expect(within(part!).getByRole("heading", { level: 4 }).textContent).toBe(
    "연결",
  );
  expect(within(part!).getByText("연결 설명")).toBeInTheDocument();
  expect(within(part!).getByText("AI 생성·미검수")).toBeInTheDocument();
  // 색 번호는 바깥 카드에만 원문 순서로 매기고, 구성 문법은 바깥 카드 색이다.
  expect(within(part!).getByText("て").className).toContain("highlight-0");
  expect(within(past!).getByText("た").className).toContain("highlight-1");
  const marks = document.querySelectorAll(".original mark");
  expect([...marks].map((mark) => mark.textContent)).toEqual([
    "てしまっ",
    "た",
  ]);
  expect(marks[0]!.className).toContain("highlight-0");
});

test("대응 표현이 있으면 제목과 설명 사이에 한 줄로 보이고, 미검수 배지는 카드에 하나다", async () => {
  respondWith(200, {
    translation_ko: "친구를 만났다",
    grammar: [
      withParts(
        {
          ...grammarItem(1, 6, "동작의 상대"),
          korean_equivalent: "~에게 · ~을/를 (会う·乗る 등)",
          korean_equivalent_review_status: "pending",
        },
        {
          ...grammarItem(4, 6, "정중한 과거"),
          korean_equivalent: "~었습니다",
          korean_equivalent_review_status: "pending",
        },
      ),
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "友達に会いました");

  const [card] = await screen.findAllByRole("listitem");
  const line = within(card!).getByText("~에게 · ~을/를 (会う·乗る 등)");
  expect(line.className).toContain("korean-equivalent");
  // 배지 줄 → 제목 줄 → 대응 표현 줄 → 설명 순서다(DESIGN.md 카드 줄 구조).
  const heading = within(card!).getByRole("heading", { level: 3 });
  const explanation = within(card!).getByText("동작의 상대 설명");
  expect(
    heading.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    line.compareDocumentPosition(explanation) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  const [part] = within(
    within(card!).getByRole("list", { name: "구성 문법" }),
  ).getAllByRole("listitem");
  expect(within(part!).getByText("~었습니다")).toBeInTheDocument();
  // 대응 표현은 용법의 일부라 따로 배지를 달지 않는다.
  expect(within(part!).getAllByText("AI 생성·미검수")).toHaveLength(1);
});

test("승인된 용법에 미검수 대응 표현이 있으면 그 줄에만 'AI 생성·미검수' 배지를 단다", async () => {
  respondWith(200, {
    translation_ko: "친구를 만났다",
    grammar: [
      {
        ...grammarItem(1, 2, "동작의 상대"),
        review_status: "approved",
        korean_equivalent: "~에게",
        korean_equivalent_review_status: "pending",
      },
      {
        ...grammarItem(4, 6, "정중한 과거"),
        review_status: "approved",
        korean_equivalent: "~었습니다",
        korean_equivalent_review_status: "approved",
      },
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "友達に会いました");

  const [pending, approved] = await screen.findAllByRole("listitem");
  const line = pending!.querySelector(".korean-equivalent")!;
  expect(
    within(line as HTMLElement).getByText("AI 생성·미검수"),
  ).toBeInTheDocument();
  expect(within(pending!).getAllByText("AI 생성·미검수")).toHaveLength(1);
  expect(within(approved!).queryByText("AI 생성·미검수")).toBeNull();
});

test("대응 표현이 없는 카드에는 대응 표현 줄이 없다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は")],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  await screen.findAllByRole("listitem");
  expect(document.querySelector(".korean-equivalent")).toBeNull();
});

test("품사 태그와 기능 태그는 제목과 대응 표현 사이 태그 줄에 보이고, 미검수 배지는 카드에 하나다", async () => {
  respondWith(200, {
    translation_ko: "달리고 있다",
    grammar: [
      {
        ...grammarItem(2, 5, "진행"),
        korean_equivalent: "~고 있다",
        korean_equivalent_review_status: "pending",
        pos_tags: ["particle", "verb"],
        function_tags: ["progressive"],
        function_tags_review_status: "pending",
      },
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "走っている");

  const [card] = await screen.findAllByRole("listitem");
  const tags = within(card!).getByRole("list", { name: "태그" });
  expect(
    within(tags)
      .getAllByRole("listitem")
      .map((tag) => tag.textContent),
  ).toEqual(["조사", "동사", "진행"]);
  // 배지 줄 → 제목 줄 → 태그 줄 → 대응 표현 줄 순서다(DESIGN.md 카드 줄 구조).
  const heading = within(card!).getByRole("heading", { level: 3 });
  const equivalent = within(card!).getByText("~고 있다");
  expect(
    heading.compareDocumentPosition(tags) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    tags.compareDocumentPosition(equivalent) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  // 기능 태그는 용법의 일부라 따로 배지를 달지 않는다.
  expect(within(card!).getAllByText("AI 생성·미검수")).toHaveLength(1);
});

test("승인된 용법에 미검수 기능 태그가 있으면 태그 줄에 배지 하나를 달고, 태그가 없으면 줄이 없다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [
      {
        ...grammarItem(1, 2, "주제 は"),
        review_status: "approved",
        pos_tags: ["particle"],
        function_tags: ["topic", "subject"],
        function_tags_review_status: "pending",
      },
      { ...grammarItem(4, 6, "정중 です"), review_status: "approved" },
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  await screen.findAllByRole("listitem");
  const [tagged, plain] = grammarCards();
  const tags = within(tagged!).getByRole("list", { name: "태그" });
  expect(tags.parentElement!.textContent).toContain("AI 생성·미검수");
  expect(within(tagged!).getAllByText("AI 생성·미검수")).toHaveLength(1);
  expect(within(plain!).queryByRole("list", { name: "태그" })).toBeNull();
});

test("하위 박스에도 회화체 배지와 원형 안내, 판단하지 못함, 다른 해석이 보통 카드처럼 붙는다", async () => {
  respondWith(200, {
    translation_ko: "먹어 버렸다",
    grammar: [
      withParts(
        grammarItem(0, 7, "전체"),
        {
          ...grammarItem(0, 2, "먹다"),
          state: "unresolved",
          explanation_ko: null,
        },
        {
          ...grammarItem(2, 3, "연결"),
          state: "divergent",
          alternatives: [alternativeItem("이유", "먹어서 버렸다")],
        },
        {
          ...grammarItem(2, 7, "완료"),
          register: "colloquial",
          variant_of: "てしまう",
        },
      ),
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "食べてしまった");

  await screen.findByRole("tab", { name: "문법 4" });
  const [unresolved, divergent, colloquial] = [
    ...screen
      .getByRole("list", { name: "구성 문법" })
      .querySelectorAll<HTMLElement>("li.grammar-part"),
  ];
  expect(within(unresolved!).getByText("판단하지 못함")).toBeInTheDocument();
  expect(divergent).toHaveClass("divergent");
  expect(
    within(divergent!).getByText("다른 해석: 이유 — 먹어서 버렸다"),
  ).toBeInTheDocument();
  expect(within(colloquial!).getByText("회화체")).toHaveClass("badge-neutral");
  expect(
    within(colloquial!).getByText("「てしまう」의 회화체"),
  ).toBeInTheDocument();
});

test("드래그 범위가 구성 문법과만 겹쳐도 바깥 카드를 올리고, 선택 링은 바깥 카드에만 둔다", async () => {
  respondWith(200, {
    translation_ko: "먹어 버렸다",
    grammar: [
      grammarItem(0, 2, "먹다"),
      withParts(grammarItem(2, 6, "완료"), grammarItem(2, 3, "연결")),
    ],
    words: [],
  });
  render(<App />);

  // て만 골랐다.
  await sendSelected(panelWindowId, "食べてしまった", 2, 3);

  await screen.findByRole("tab", { name: "문법 3" });
  const [outer, other] = grammarCards();
  expect(cardHeading(outer!)).toBe("완료");
  expect(outer).toHaveClass("dragged");
  expect(within(outer!).getAllByText("드래그한 부분")).toHaveLength(1);
  expect(other).not.toHaveClass("dragged");
  const part = outer!.querySelector<HTMLElement>("li.grammar-part")!;
  expect(part).not.toHaveClass("dragged");
  expect(within(part).queryByText("드래그한 부분")).toBeNull();
});

test("먼저 온 확정 문법은 평평하게 보이고, 분석이 오면 하위 박스로 바뀐다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "食べてしまった");

  stream.push({
    type: "grammar",
    grammar: [
      approvedGrammarItem(2, 3, "연결"),
      approvedGrammarItem(2, 6, "완료"),
    ],
  });

  await waitFor(() =>
    expect(grammarCards().map(cardHeading)).toEqual(["연결", "완료"]),
  );

  stream.push({ type: "translation", translation_ko: "먹어 버렸다", ruby: [] });
  stream.push({
    type: "analysis",
    translation_ko: "먹어 버렸다",
    grammar: [
      withParts(
        approvedGrammarItem(2, 6, "완료"),
        approvedGrammarItem(2, 3, "연결"),
      ),
    ],
    words: [],
  });
  stream.end();

  await screen.findByRole("tab", { name: "문법 2" });
  expect(grammarCards().map(cardHeading)).toEqual(["완료"]);
  expect(
    within(screen.getByRole("list", { name: "구성 문법" })).getByRole(
      "heading",
      { level: 4 },
    ).textContent,
  ).toBe("연결");
});

test("같은 용법이 두 자리에 걸리면 문법 카드는 한 장이고, 두 자리 형광펜은 카드 칩과 같은 색이다", async () => {
  respondWith(200, {
    translation_ko: "고양이가 개를 좋아한다",
    grammar: [
      grammarItem(1, 2, "주어 が"),
      grammarItem(3, 4, "주어 が"),
      grammarItem(4, 6, "형용동사"),
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "猫が犬が好き");

  // 문법 개수는 보이는 카드 수다.
  await screen.findByRole("tab", { name: "문법 2" });
  expect(grammarCards().map(cardHeading)).toEqual(["주어 が", "형용동사"]);
  const marks = [...document.querySelectorAll(".original mark")];
  expect(marks.map((mark) => mark.textContent)).toEqual(["が", "が", "好き"]);
  expect(marks[0]!.className).toContain("highlight-0");
  expect(marks[1]!.className).toContain("highlight-0");
  expect(marks[2]!.className).toContain("highlight-1");
  expect(within(cardOf("주어 が")).getByText("が").className).toContain(
    "highlight-0",
  );
});

test("합친 자리 중 하나라도 드래그 범위와 겹치면 그 카드에 '드래그한 부분'을 달고 위로 올린다", async () => {
  respondWith(200, {
    translation_ko: "고양이가 개를 좋아한다",
    grammar: [
      grammarItem(0, 1, "고양이"),
      grammarItem(1, 2, "주어 が"),
      grammarItem(3, 4, "주어 が"),
    ],
    words: [],
  });
  render(<App />);

  // 두 번째 が만 골랐다.
  await sendSelected(panelWindowId, "猫が犬が好き", 3, 4);

  await screen.findByRole("heading", { name: "고양이" });
  expect(grammarCards().map(cardHeading)).toEqual(["주어 が", "고양이"]);
  expect(
    within(cardOf("주어 が")).getByText("드래그한 부분"),
  ).toBeInTheDocument();
});

test("구성 문법의 판정이나 대안이 다르면 같은 용법 카드도 합치지 않는다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [
      withParts(
        approvedGrammarItem(0, 2, "완료"),
        approvedGrammarItem(0, 1, "연결"),
      ),
      withParts(approvedGrammarItem(2, 4, "완료"), {
        ...grammarItem(2, 3, "연결"),
        state: "divergent",
        alternatives: [alternativeItem("대안", "대안 번역")],
      }),
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "一二三四");

  await screen.findAllByRole("heading", { name: "완료" });
  expect(grammarCards().map(cardHeading)).toEqual(["완료", "완료"]);
  expect(screen.getByText("다른 해석: 대안 — 대안 번역")).toBeInTheDocument();
});

test("해석 갈림·미확정·확인 중 카드는 같은 이름이어도 합치지 않는다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [
      {
        ...grammarItem(0, 1, "갈림"),
        state: "divergent",
        alternatives: [alternativeItem("대안", "대안 번역")],
      },
      {
        ...grammarItem(1, 2, "갈림"),
        state: "divergent",
        alternatives: [alternativeItem("대안", "대안 번역")],
      },
      {
        ...grammarItem(2, 3, "미확정"),
        state: "unresolved",
        explanation_ko: null,
      },
      {
        ...grammarItem(3, 4, "미확정"),
        state: "unresolved",
        explanation_ko: null,
      },
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "一二三四");

  await screen.findAllByRole("heading", { name: "갈림" });
  expect(grammarCards().map(cardHeading)).toEqual([
    "갈림",
    "갈림",
    "미확정",
    "미확정",
  ]);
});

test("미검수 배지는 제목 위 배지 줄에 있고, 배지도 '드래그한 부분'도 없는 카드에는 배지 줄이 없다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [
      { ...grammarItem(1, 2, "주제 は"), register: "colloquial" },
      approvedGrammarItem(4, 6, "정중 です"),
    ],
    words: [],
  });
  render(<App />);

  // 私만 골라 두 카드 모두 드래그 범위 밖이다.
  await sendSelected(panelWindowId, "私は学生です。", 0, 1);

  await screen.findByRole("heading", { name: "정중 です" });
  const pending = cardOf("주제 は");
  const badges = pending.querySelector(".card-badges")!;
  expect(
    within(badges as HTMLElement).getByText("AI 생성·미검수"),
  ).toBeInTheDocument();
  expect(within(badges as HTMLElement).getByText("회화체")).toBeInTheDocument();
  // 배지 줄이 카드 첫 줄이고, 제목 줄에는 배지가 없다.
  expect(pending.firstElementChild).toBe(badges);
  const head = within(pending).getByRole("heading").parentElement!;
  expect(head.querySelector("[class^=badge]")).toBeNull();
  expect(cardOf("정중 です").querySelector(".card-badges")).toBeNull();
});

test("확인 중 카드도 미검수 배지와 '드래그한 부분'을 배지 줄에 둔다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await sendSelected(panelWindowId, "一二", 0, 1);

  stream.push({
    type: "grammar",
    grammar: [],
    checking: [
      {
        ...checkingItem(0, 1, "후보"),
        candidates: [{ name: "후보", review_status: "pending" }],
      },
    ],
  });

  const card = (await screen.findByRole("heading", { name: "후보" })).closest(
    "li",
  )!;
  const badges = card.querySelector(".card-badges") as HTMLElement;
  expect(card.firstElementChild).toBe(badges);
  expect(within(badges).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(within(badges).getByText("드래그한 부분")).toBeInTheDocument();
});

test("단어 카드는 배지 줄 → 표제 → 태그 → 뜻 순서다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [],
    words: [
      wordItem(0, 1, "一", "いち", { origin: "llm", status: "pending" }),
      wordItem(1, 2, "二", "に"),
    ],
  });
  render(<App />);
  await sendSelected(panelWindowId, "一二", 0, 1);

  fireEvent.click(await screen.findByRole("tab", { name: "단어 2" }));

  const [llm, reviewed] = within(screen.getByRole("list", { name: "단어" }))
    .getAllByRole("listitem")
    .filter((row) => row.classList.contains("word-row"));
  expect([...llm!.children].map((child) => child.className)).toEqual([
    "card-badges",
    "word-head",
    "word-tags",
    "word-meaning",
    // 카드 맨 아래의 '이름으로 지정'(#136)
    "name-actions",
  ]);
  const badges = llm!.firstElementChild as HTMLElement;
  expect(within(badges).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(within(badges).getByText("드래그한 부분")).toBeInTheDocument();
  expect(reviewed!.querySelector(".card-badges")).toBeNull();
});

describe("로그인과 확장 연결(#109)", () => {
  test("연결하지 않았으면 로그인 안내를 보이고, 버튼이 웹 연결 화면을 새 탭으로 연다", async () => {
    await fakeBrowser.storage.local.clear();
    const openTab = vi.spyOn(fakeBrowser.tabs, "create");
    render(<App />);

    const button = await screen.findByRole("button", {
      name: "로그인하고 연결하기",
    });
    expect(
      screen.getByRole("heading", { name: "로그인이 필요해요" }),
    ).toBeInTheDocument();
    fireEvent.click(button);

    expect(openTab).toHaveBeenCalledWith({ url: `${WEB_ORIGIN}/connect` });
  });

  test("분석 요청에 토큰을 Bearer로 붙인다", async () => {
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    render(<App />);

    await send(panelWindowId, "私は学生です。");

    expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
    const init = fetchMock.mock.calls[0]![1];
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer extension-token",
    );
  });

  test("서버가 로그인이 필요하다고 하면 토큰을 지우고 로그인 안내를 보인다", async () => {
    respondWith(401, { error: "AUTH:LOGIN_REQUIRED" });
    render(<App />);

    await send(panelWindowId, "私は学生です。");

    expect(
      await screen.findByRole("heading", { name: "로그인이 필요해요" }),
    ).toBeInTheDocument();
    expect(await loadToken()).toBeUndefined();
  });

  test("연결이 끝나면 안내를 닫고 기다리던 문장을 다시 분석한다", async () => {
    await fakeBrowser.storage.local.clear();
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    render(<App />);
    await send(panelWindowId, "私は学生です。");
    await screen.findByRole("heading", { name: "로그인이 필요해요" });
    expect(fetchMock).not.toHaveBeenCalled();

    await saveToken("new-token");

    expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "로그인이 필요해요" }),
    ).not.toBeInTheDocument();
  });

  test("로그아웃하면 서버에서 이 토큰을 폐기하고 로그인 안내를 보인다", async () => {
    const fetchMock = respondWith(204, {});
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "로그아웃" }));

    expect(
      await screen.findByRole("heading", { name: "로그인이 필요해요" }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]![0]).toMatch(
      /\/api\/auth\/extension-tokens\/revoke\/$/,
    );
    expect(await loadToken()).toBeUndefined();
  });

  test("로그아웃하면 보던 원문과 결과를 지워, 다음에 연결한 사람에게 보이지 않는다", async () => {
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(
        url.endsWith("/revoke/")
          ? new Response(null, { status: 204 })
          : json(200, analysis("나는 학생입니다.")),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await send(panelWindowId, "私は学生です。");
    await screen.findByText("나는 학생입니다.");

    fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));
    await screen.findByRole("heading", { name: "로그인이 필요해요" });
    await saveToken("someone-else-token");

    await screen.findByRole("button", { name: "로그아웃" });
    expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
    expect(screen.queryByText("나는 학생입니다.")).not.toBeInTheDocument();
    // 다시 분석하지도 않는다.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("다시 연결한 뒤에 옛 토큰의 401이 와도 그 문장을 새 토큰으로 다시 분석한다", async () => {
    let rejectOld!: (response: Response) => void;
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      const auth = (init.headers as Record<string, string>).Authorization;
      if (auth === "Bearer extension-token") {
        return new Promise<Response>((resolve) => (rejectOld = resolve));
      }
      return Promise.resolve(json(200, analysis("나는 학생입니다.")));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await send(panelWindowId, "私は学生です。");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await saveToken("new-token");
    rejectOld(json(401, { error: "AUTH:LOGIN_REQUIRED" }));

    expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
    expect(await loadToken()).toBe("new-token");
  });

  test("웹에서 로그아웃해도 보던 원문과 결과를 지운다", async () => {
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    render(<App />);
    await send(panelWindowId, "私は学生です。");
    await screen.findByText("나는 학생입니다.");

    await handleExternalMessage(
      { type: "disconnect" },
      `${WEB_ORIGIN}/connect`,
    );
    await screen.findByRole("heading", { name: "로그인이 필요해요" });
    await saveToken("someone-else-token");

    await screen.findByRole("button", { name: "로그아웃" });
    expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("이미 지나간 회차의 401이 늦게 와도 지금 회차를 다시 보내지 않는다", async () => {
    let rejectOld!: (response: Response) => void;
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      const { text } = JSON.parse(init.body as string) as { text: string };
      if (text === "古い文です。") {
        return new Promise<Response>((resolve) => (rejectOld = resolve));
      }
      return Promise.resolve(json(200, analysis("새 문장")));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await send(panelWindowId, "古い文です。");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    // 다시 연결하고 새 문장을 고른다.
    await saveToken("new-token");
    await send(panelWindowId, "新しい文です。");
    await screen.findByText("새 문장");

    rejectOld(json(401, { error: "AUTH:LOGIN_REQUIRED" }));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("새 문장")).toBeInTheDocument();
  });

  test("로그아웃 전에 들어와 남아 있던 분석 요청은 다음에 연결한 사람에게 분석하지 않는다", async () => {
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    // 패널이 닫힌 동안 들어온 요청이 세션 저장소에 남아 있다.
    await send(panelWindowId, "私は学生です。");
    await signOut();
    await saveToken("someone-else-token", "someone-else");

    render(<App />);
    await screen.findByRole("button", { name: "로그아웃" });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("로그아웃 전에 시작한 문장 추출이 늦게 저장돼도 버린다", async () => {
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    render(<App />);
    await screen.findByRole("button", { name: "로그아웃" });
    const startedAt = Date.now() - 1000;
    await signOut();
    await saveToken("someone-else-token", "someone-else");

    await requestAnalysis(
      panelWindowId,
      [{ text: "私は学生です。", selection: { start: 0, end: 7 } }],
      startedAt,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("이름 지정(#136)", () => {
  // 두 문장에 같은 표기 春이 나온다. 루비는 SudachiPy 읽기다.
  function respondWithSpring() {
    return respondPerSentence({
      春が来た: () =>
        json(200, {
          translation_ko: "봄이 왔다",
          grammar: [],
          words: [wordItem(0, 1, "春", "はる")],
          ruby: [rubyItem(0, 1, "はる")],
        }),
      春の雨: () =>
        json(200, {
          translation_ko: "봄비",
          grammar: [],
          words: [wordItem(0, 1, "春", "はる"), wordItem(2, 3, "雨", "あめ")],
          ruby: [rubyItem(0, 1, "はる"), rubyItem(2, 3, "あめ")],
        }),
    });
  }

  async function openWords() {
    fireEvent.click(await screen.findByRole("tab", { name: /^단어/ }));
  }

  async function designate(reading?: string) {
    fireEvent.click(screen.getByRole("button", { name: "이름으로 지정" }));
    if (reading !== undefined) {
      fireEvent.change(screen.getByRole("textbox", { name: "읽기" }), {
        target: { value: reading },
      });
    }
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
  }

  test("지정하면 열린 모든 문장 페이지의 같은 표기가 이름 행이 되고 다시 분석하지 않는다", async () => {
    const fetchMock = respondWithSpring();
    vi.mocked(saveName).mockResolvedValue({ surface: "春", reading: "はるか" });
    render(<App />);
    await send(panelWindowId, "春が来た", "春の雨");
    await openWords();

    await designate("ハルカ");

    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(saveName).toHaveBeenCalledWith("春", "ハルカ");
    expect(screen.queryByText("春 뜻")).not.toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はるか"]]);
    fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));
    await openWords();
    expect(screen.getAllByText("내가 지정한 이름")).toHaveLength(1);
    expect(screen.getByText("雨 뜻")).toBeInTheDocument();
    expect(rubies()).toEqual([
      ["春", "はるか"],
      ["雨", "あめ"],
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("읽기 입력에 SudachiPy 읽기를 채우고 사전 읽기 칩을 고를 수 있다", async () => {
    respondWithSpring();
    vi.mocked(saveName).mockResolvedValue({ surface: "春", reading: "はる" });
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    fireEvent.click(screen.getByRole("button", { name: "이름으로 지정" }));

    const input = screen.getByRole("textbox", { name: "읽기" });
    expect(input).toHaveValue("はる");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "はる" }));
    expect(input).toHaveValue("はる");
  });

  test("가나가 아닌 읽기는 그 자리에서 오류를 보이고 저장하지 않는다", async () => {
    respondWithSpring();
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    await designate("haru");

    expect(
      screen.getByText("읽기는 가나로만 입력해 주세요"),
    ).toBeInTheDocument();
    expect(saveName).not.toHaveBeenCalled();
  });

  test("저장에 실패하면 화면을 바꾸지 않고 실패 문구를 보인다", async () => {
    respondWithSpring();
    vi.mocked(saveName).mockRejectedValue(new Error("실패"));
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    await designate("はる");

    expect(
      await screen.findByText(
        "이름을 저장하지 못했습니다. 다시 시도해 주세요.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
    expect(screen.getByText("春 뜻")).toBeInTheDocument();
  });

  test("'사전 단어 보기'는 그 자리만 카드와 루비를 바꾸고 서버에 묻지 않는다", async () => {
    const fetchMock = respondWithSpring();
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();
    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "しゅん"]]);

    fireEvent.click(screen.getByRole("button", { name: "사전 단어 보기" }));

    expect(screen.getByText("春 뜻")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はる"]]);
    fireEvent.click(screen.getByRole("button", { name: "사전 단어 보기" }));
    expect(screen.getByText("내가 지정한 이름")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(saveName).not.toHaveBeenCalled();
    expect(removeName).not.toHaveBeenCalled();
  });

  function respondWithSpringNames(nameSpans: { start: number; end: number }[]) {
    return respondPerSentence({
      春が来た: () =>
        json(200, {
          translation_ko: "봄이 왔다",
          grammar: [],
          words: [wordItem(0, 1, "春", "はる")],
          ruby: [rubyItem(0, 1, "はる")],
          name_spans: nameSpans,
        }),
    });
  }

  test("이름 구간 밖의 지정한 이름은 사전 단어 행으로 시작하고 토글로 이름 행이 된다", async () => {
    respondWithSpringNames([]);
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    expect(await screen.findByText("春 뜻")).toBeInTheDocument();
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はる"]]);
    const toggle = screen.getByRole("button", { name: "사전 단어 보기" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(toggle);

    expect(screen.getByText("내가 지정한 이름")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "しゅん"]]);
    expect(
      screen.getByRole("button", { name: "사전 단어 보기" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  test("이름 구간 안의 지정한 이름은 이름 행으로 시작한다", async () => {
    respondWithSpringNames([{ start: 0, end: 1 }]);
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "しゅん"]]);
  });

  test("'읽기 고치기'로 읽기를 바꾼다", async () => {
    respondWithSpring();
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    vi.mocked(saveName).mockResolvedValue({ surface: "春", reading: "はる" });
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    fireEvent.click(await screen.findByRole("button", { name: "읽기 고치기" }));
    fireEvent.change(screen.getByRole("textbox", { name: "읽기" }), {
      target: { value: "はる" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(rubies()).toEqual([["春", "はる"]]));
    expect(saveName).toHaveBeenCalledWith("春", "はる");
    expect(screen.getByText("내가 지정한 이름")).toBeInTheDocument();
  });

  test("'지정 해제' 뒤 같은 표기가 단어 카드와 SudachiPy 루비로 돌아간다", async () => {
    respondWithSpring();
    vi.mocked(fetchNames).mockResolvedValue([
      { surface: "春", reading: "しゅん" },
    ]);
    vi.mocked(removeName).mockResolvedValue();
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    fireEvent.click(await screen.findByRole("button", { name: "지정 해제" }));

    expect(await screen.findByText("春 뜻")).toBeInTheDocument();
    expect(removeName).toHaveBeenCalledWith("春");
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はる"]]);
  });

  // 패널을 연 채 다른 계정으로 연결을 바꾼다. 보던 문장은 지워지므로 같은 문장을 다시 보낸다.
  async function switchAccount() {
    await saveToken("other-token", "other@example.com");
    await waitFor(() =>
      expect(screen.queryByText("春が来た")).not.toBeInTheDocument(),
    );
    await send(panelWindowId, "春が来た");
    await openWords();
  }

  function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>((r) => (resolve = r));
    return { promise, resolve };
  }

  test("계정을 바꾸면 새 계정의 목록을 받고, 이전 계정의 늦은 목록은 버린다", async () => {
    respondWithSpring();
    const old = deferred<{ surface: string; reading: string | null }[]>();
    vi.mocked(fetchNames)
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue([]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    await switchAccount();
    old.resolve([{ surface: "春", reading: "しゅん" }]);

    expect(await screen.findByText("春 뜻")).toBeInTheDocument();
    await waitFor(() => expect(fetchNames).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
  });

  test("이전 계정에서 보낸 저장의 늦은 응답은 새 계정 화면에 쓰지 않는다", async () => {
    respondWithSpring();
    const save = deferred<{ surface: string; reading: string | null }>();
    vi.mocked(saveName).mockReturnValue(save.promise);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();
    await designate("はる");

    await switchAccount();
    save.resolve({ surface: "春", reading: "はる" });

    expect(await screen.findByText("春 뜻")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("내가 지정한 이름")).not.toBeInTheDocument();
  });

  test("목록을 받는 사이 저장한 이름은 늦게 온 옛 목록에 덮이지 않는다", async () => {
    respondWithSpring();
    const first = deferred<{ surface: string; reading: string | null }[]>();
    vi.mocked(fetchNames)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue([{ surface: "春", reading: "はる" }]);
    vi.mocked(saveName).mockResolvedValue({ surface: "春", reading: "はる" });
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();
    await designate("はる");
    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();

    // 저장 전에 읽은 목록이 늦게 온다.
    first.resolve([]);

    await waitFor(() => expect(fetchNames).toHaveBeenCalledTimes(2));
    expect(screen.getByText("내가 지정한 이름")).toBeInTheDocument();
  });

  test("읽기 없이 지정한 이름은 SudachiPy 루비를 그대로 단다", async () => {
    respondWithSpring();
    vi.mocked(fetchNames).mockResolvedValue([{ surface: "春", reading: null }]);
    render(<App />);
    await send(panelWindowId, "春が来た");
    await openWords();

    expect(await screen.findByText("내가 지정한 이름")).toBeInTheDocument();
    expect(rubies()).toEqual([["春", "はる"]]);
  });
});
