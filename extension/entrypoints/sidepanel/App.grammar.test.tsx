import { expect, test, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import App from "./App";
import {
  approvedGrammarItem,
  cardOf,
  checkingItem,
  grammarItem,
  ndjson,
  panelWindowId,
  respondWith,
  send,
  streamed,
  withParts,
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

test("원문의 문법 구간에 형광펜을 칠하고, 카드 칩에 패턴 이름을 보인다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [
      grammarItem(1, 2, "주제 は", "は"),
      grammarItem(4, 6, "정중 です", "です"),
    ],
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
  // 색은 한 가지라 구간·카드마다 바꾸지 않는다(#354).
  expect(marks[1]!.className).toBe(marks[0]!.className);
  expect(chips[1]!.className).toBe(chips[0]!.className);
});

test("문법이 없으면 문법 칸 자리에 '문법 요소 없음'을 보인다", async () => {
  respondWith(200, { translation_ko: "도쿄", grammar: [], words: [] });
  render(<App />);

  await send(panelWindowId, "東京");

  expect(await screen.findByText("문법 요소 없음")).toBeInTheDocument();
});

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

test("확인 중 카드는 번역이 와도 남고, 해당 없음으로 판정되면 사라진다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "彼が来ている");

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
  ).toEqual(["주격", "진행"]);

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

test("후보가 하나인 확인 중 카드는 판정 전에도 그 용법의 설명·대응 표현·태그를 보이고, 판정이 오면 확인 중만 뗀다(#203)", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "彼が来ている");

  const usage = {
    ...grammarItem(3, 6, "진행"),
    korean_equivalent: "~고 있다",
    korean_equivalent_review_status: "pending",
    pos_tags: ["particle", "verb"],
  };
  const { start, end, state: _state, ...fields } = usage;
  stream.push({
    type: "grammar",
    grammar: [],
    checking: [
      {
        start,
        end,
        candidates: [{ name: "진행", review_status: "pending" }],
        usage: fields,
      },
    ],
  });

  const [card] = await screen.findAllByRole("listitem");
  expect(card).toHaveClass("checking");
  expect(within(card!).getByRole("heading").textContent).toBe("진행");
  expect(within(card!).getByText("확인 중")).toBeInTheDocument();
  expect(within(card!).getByText("진행 설명")).toBeInTheDocument();
  expect(within(card!).getByText("~고 있다")).toBeInTheDocument();
  expect(within(card!).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(card!.querySelector(".skeleton")).toBeNull();
  // 판정 전이라 원문은 형광펜이 아니라 점선 밑줄이다.
  expect(document.querySelectorAll(".original mark.checking")).toHaveLength(1);
  expect(document.querySelectorAll(".original mark.highlight")).toHaveLength(0);

  stream.push({
    type: "analysis",
    translation_ko: "그가 와 있다",
    grammar: [usage],
    words: [],
  });
  stream.end();

  expect(
    await screen.findByRole("tab", { name: "문법 1" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("확인 중")).not.toBeInTheDocument();
  expect(screen.getByText("진행 설명")).toBeInTheDocument();
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

function grammarCards() {
  return screen
    .getAllByRole("listitem")
    .filter((li) => li.classList.contains("grammar-card"));
}

function cardHeading(card: HTMLElement) {
  return within(card).getByRole("heading", { level: 3 }).textContent;
}

test("구성 문법은 바깥 카드 안의 하위 박스로 보인다", async () => {
  respondWith(200, {
    translation_ko: "먹어 버렸다",
    grammar: [
      withParts(
        grammarItem(2, 6, "완료", "てしまう"),
        grammarItem(2, 3, "연결", "て"),
      ),
      grammarItem(6, 7, "과거", "た"),
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
  expect(within(part!).getByText("て").className).toBe(
    within(past!).getByText("た").className,
  );
  const marks = document.querySelectorAll(".original mark");
  expect([...marks].map((mark) => mark.textContent)).toEqual([
    "てしまっ",
    "た",
  ]);
});

test("대응 표현을 보이고, 미검수 배지는 카드에 하나다", async () => {
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
  expect(
    within(card!).getByText("~에게 · ~을/를 (会う·乗る 등)"),
  ).toBeInTheDocument();
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

test("대응 표현 앞에 '뜻', 설명 앞에 '설명' 라벨을 달고 하위 박스도 같다", async () => {
  respondWith(200, {
    translation_ko: "친구를 만났다",
    grammar: [
      withParts(
        {
          ...grammarItem(1, 6, "동작의 상대"),
          korean_equivalent: "~에게",
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
  const [part] = within(
    within(card!).getByRole("list", { name: "구성 문법" }),
  ).getAllByRole("listitem");
  for (const [box, equivalent, explanation] of [
    [card!, "~에게", "동작의 상대 설명"],
    [part!, "~었습니다", "정중한 과거 설명"],
  ] as const) {
    const lines = within(box);
    expect(within(lines.getByText(equivalent)).getByText("뜻")).toBeVisible();
    expect(
      within(lines.getByText(explanation)).getByText("설명"),
    ).toBeVisible();
  }
});

test("판단하지 못함 줄과 대응 표현 없는 카드에는 라벨이 없다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [
      grammarItem(1, 2, "주제 は"),
      { ...grammarItem(4, 6, "정중 です"), state: "unresolved" },
    ],
    words: [],
  });
  render(<App />);

  await send(panelWindowId, "私は学生です。");

  await screen.findAllByRole("listitem");
  const [plain, unresolved] = grammarCards();
  expect(within(plain!).queryByText("뜻")).toBeNull();
  expect(within(unresolved!).getByText("판단하지 못함")).toBeVisible();
  expect(within(unresolved!).queryByText("설명")).toBeNull();
});

test("품사 태그와 기능 태그를 태그 줄에 보이고, 미검수 배지는 카드에 하나다", async () => {
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

test("같은 용법이 두 자리에 걸리면 문법 카드는 한 장이다", async () => {
  respondWith(200, {
    translation_ko: "고양이가 개를 좋아한다",
    grammar: [
      grammarItem(1, 2, "주어 が", "が"),
      grammarItem(3, 4, "주어 が", "が"),
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
