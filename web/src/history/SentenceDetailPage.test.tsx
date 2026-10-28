import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { GrammarItem, SentenceDetail, WordItem } from "./analysis";
import SentenceDetailPage from "./SentenceDetailPage";

let responses: Record<string, () => Response>;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const grammar = (fields: Partial<GrammarItem>): GrammarItem => ({
  start: 0,
  end: 0,
  pattern_name: "",
  state: "decided",
  name: "",
  explanation_ko: null,
  korean_equivalent: null,
  korean_equivalent_review_status: null,
  pos_tags: [],
  function_tags: [],
  function_tags_review_status: null,
  review_status: "approved",
  register: "standard",
  variant_of: null,
  ...fields,
});

const word = (fields: Partial<WordItem>): WordItem => ({
  start: 0,
  end: 0,
  dictionary_form: "",
  reading: "",
  tags: [],
  in_dictionary: true,
  sense: null,
  ...fields,
});

// 私は3人で走っている。
const DETAIL: SentenceDetail = {
  id: 7,
  text: "私は3人で走っている。",
  analyzed_at: "2026-10-28T03:00:00Z",
  translation_ko: "나는 3명이서 달리고 있다.",
  ruby: [{ start: 0, end: 1, reading: "わたし" }],
  grammar: [
    grammar({
      start: 3,
      end: 5,
      pattern_name: "人で",
      name: "인원",
      explanation_ko: "함께하는 사람 수를 나타낸다",
      review_status: "pending",
    }),
    grammar({
      start: 6,
      end: 10,
      pattern_name: "ている",
      name: "진행",
      explanation_ko: "동작이 이어지고 있음을 나타낸다",
      pos_tags: ["auxiliary_verb"],
      function_tags: ["progressive"],
      function_tags_review_status: "pending",
      parts: [grammar({ start: 7, end: 8, pattern_name: "て", name: "접속" })],
    }),
  ],
  words: [
    word({
      start: 0,
      end: 1,
      dictionary_form: "私",
      reading: "わたし",
      tags: ["pronoun"],
      sense: {
        tags: [],
        gloss_en: ["I"],
        origin: "jmdict",
        status: "approved",
        meaning_ko: "나",
        meaning_status: "ai",
      },
    }),
  ],
  name_spans: [],
};

beforeEach(() => {
  responses = {
    "/api/auth/me/": () =>
      json({ user: { email: "me@example.com", account: "42" } }),
    "/api/my-sentences/7/": () => json(DETAIL),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => responses[url]()),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function open(id = "7") {
  render(
    <MemoryRouter initialEntries={[`/sentences/${id}`]}>
      <Routes>
        <Route path="/sentences/:id" element={<SentenceDetailPage />} />
        <Route path="/connect" element={<p>로그인 화면</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

test("원문, 번역, 문법 카드, 단어 카드를 보인다", async () => {
  open();

  expect(await screen.findByText("나는 3명이서 달리고 있다.")).toBeVisible();
  const cards = within(screen.getByRole("list", { name: "문법" }))
    .getAllByRole("listitem")
    .filter((li) => li.parentElement?.getAttribute("aria-label") === "문법");
  expect(
    cards.map((c) => within(c).getByRole("heading", { level: 3 }).textContent),
  ).toEqual(["인원", "진행"]);
  // LLM이 만든 미검수 용법에만 배지를 단다.
  expect(within(cards[0]).getByText("AI 생성·미검수")).toBeInTheDocument();
  // 원문 구간이 패턴 이름과 다를 때만 문장 속 형태를 보인다.
  expect(within(cards[0]).queryByText(/문장 속 형태:/)).toBeNull();
  expect(within(cards[1]).getByText(/문장 속 형태:/)).toHaveTextContent(
    "문장 속 형태: っている",
  );
  // 승인된 용법에 나중에 채운 미검수 기능 태그는 태그 줄에 배지 하나를 단다.
  const tags = within(cards[1]).getByRole("list", { name: "태그" });
  expect(
    within(tags)
      .getAllByRole("listitem")
      .map((t) => t.textContent),
  ).toEqual(["조동사", "진행"]);
  expect(within(cards[1]).getAllByText("AI 생성·미검수")).toHaveLength(1);
  expect(
    within(within(cards[1]).getByRole("list", { name: "구성 문법" })).getByRole(
      "heading",
    ),
  ).toHaveTextContent("접속");

  const words = within(screen.getByRole("list", { name: "단어" }));
  expect(words.getByRole("heading")).toHaveTextContent("私");
  expect(words.getByText("나")).toBeInTheDocument();
  // 사전 뜻을 옮긴 검수 전 한국어 뜻
  expect(words.getByText("AI 번역")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "JMdict" })).toBeInTheDocument();
});

test("내 기록에 없는 문장이면 찾지 못했다고 알린다", async () => {
  responses["/api/my-sentences/8/"] = () =>
    json({ error: "SENTENCE:NOT_FOUND" }, 404);
  open("8");

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "이 문장을 찾지 못했어요.",
  );
});

test("분석이 바뀐 기록이면 다시 분석하라고 안내한다", async () => {
  responses["/api/my-sentences/7/"] = () =>
    json({ error: "SENTENCE:OUTDATED" }, 409);
  open();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "확장 프로그램에서 이 문장을 다시 분석하면 볼 수 있어요.",
  );
});

test("로그인하지 않았으면 로그인 화면으로 간다", async () => {
  responses["/api/auth/me/"] = () => json({ user: null });
  open();

  expect(await screen.findByText("로그인 화면")).toBeInTheDocument();
});
