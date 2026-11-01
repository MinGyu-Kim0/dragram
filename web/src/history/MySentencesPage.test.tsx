import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import MySentencesPage from "./MySentencesPage";

type Call = { url: string; method: string; headers: Record<string, string> };

let calls: Call[];
let responses: Record<string, () => Response>;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const SENTENCES = [
  { id: 2, text: "猫が好きです。", analyzed_at: "2026-10-28T03:00:00Z" },
  { id: 1, text: "私は学生です。", analyzed_at: "2026-10-27T03:00:00Z" },
];

beforeEach(() => {
  calls = [];
  document.cookie = "csrftoken=csrf-value";
  responses = {
    "GET /api/auth/me/": () =>
      json({ user: { email: "me@example.com", account: "42" } }),
    "GET /api/my-sentences/": () => json({ sentences: SENTENCES }),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({
        url,
        method,
        headers: (init.headers ?? {}) as Record<string, string>,
      });
      return responses[`${method} ${url}`]();
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function open() {
  render(
    <MemoryRouter initialEntries={["/sentences"]}>
      <Routes>
        <Route path="/sentences" element={<MySentencesPage />} />
        <Route path="/connect" element={<p>로그인 화면</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const items = async () =>
  within(await screen.findByRole("list", { name: "분석한 문장" })).getAllByRole(
    "listitem",
  );

test("내가 분석한 문장을 원문과 분석 시각으로 보인다", async () => {
  open();

  const rows = await items();
  expect(rows.map((r) => r.querySelector('[lang="ja"]')?.textContent)).toEqual([
    "猫が好きです。",
    "私は学生です。",
  ]);
  expect(rows[0].querySelector("time")).toHaveAttribute(
    "datetime",
    "2026-10-28T03:00:00Z",
  );
});

test("로그인하지 않았으면 로그인 화면으로 간다", async () => {
  responses["GET /api/auth/me/"] = () => json({ user: null });
  open();

  expect(await screen.findByText("로그인 화면")).toBeInTheDocument();
  expect(calls.map((c) => c.url)).not.toContain("/api/my-sentences/");
});

test("분석한 문장이 없으면 안내한다", async () => {
  responses["GET /api/my-sentences/"] = () => json({ sentences: [] });
  open();

  expect(
    await screen.findByText("아직 분석한 문장이 없어요."),
  ).toBeInTheDocument();
});

test("한 번 확인받고 지우면 목록에서 사라진다", async () => {
  responses["DELETE /api/my-sentences/1/"] = () =>
    new Response(null, { status: 204 });
  open();
  const [, second] = await items();

  await userEvent.click(within(second).getByRole("button", { name: "지우기" }));
  expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  await userEvent.click(
    within(second).getByRole("button", { name: "이 문장 지우기" }),
  );

  const deleted = calls.find((c) => c.method === "DELETE")!;
  expect(deleted.url).toBe("/api/my-sentences/1/");
  expect(deleted.headers["X-CSRFToken"]).toBe("csrf-value");
  expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
  expect(screen.getByText("猫が好きです。")).toBeInTheDocument();
});

test("확인에서 취소하면 지우지 않는다", async () => {
  open();
  const [first] = await items();

  await userEvent.click(within(first).getByRole("button", { name: "지우기" }));
  await userEvent.click(within(first).getByRole("button", { name: "취소" }));

  expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  expect(
    within(first).getByRole("button", { name: "지우기" }),
  ).toBeInTheDocument();
});

test("지우지 못하면 문장을 남기고 알린다", async () => {
  responses["DELETE /api/my-sentences/2/"] = () =>
    json({ error: "AUTH:CSRF_FAILED" }, 403);
  open();
  const [first] = await items();

  await userEvent.click(within(first).getByRole("button", { name: "지우기" }));
  await userEvent.click(
    within(first).getByRole("button", { name: "이 문장 지우기" }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "지우지 못했어요. 다시 시도해 주세요.",
  );
  expect(screen.getByText("猫が好きです。")).toBeInTheDocument();
});

test("문장을 누르면 저장된 분석 화면으로 간다", async () => {
  open();
  const [first] = await items();

  expect(
    within(first).getByRole("link", { name: "猫が好きです。" }),
  ).toHaveAttribute("href", "/sentences/2");
});

const GRAMMAR = [
  {
    usage_id: 7,
    pattern_name: "ている",
    name: "진행",
    explanation_ko: "동작이 이어지고 있음을 나타낸다",
    korean_equivalent: "~하고 있다",
    korean_equivalent_review_status: "approved",
    review_status: "pending",
    sentences: [
      { id: 2, text: "猫が好きです。" },
      { id: 1, text: "私は学生です。" },
    ],
  },
  {
    usage_id: 3,
    pattern_name: "です",
    name: "정중",
    explanation_ko: "정중하게 단정한다",
    korean_equivalent: null,
    korean_equivalent_review_status: null,
    review_status: "approved",
    sentences: [{ id: 1, text: "私は学生です。" }],
  },
];

// 카드 안의 문장 목록 항목은 빼고 카드만 고른다.
const grammarCards = async () => {
  const list = await screen.findByRole("list", { name: "내 문법" });
  return within(list)
    .getAllByRole("listitem")
    .filter((li) => li.parentElement === list);
};

test("문장 탭이 기본이고 문법 탭은 열 때 불러온다", async () => {
  responses["GET /api/my-japanese/grammar/"] = () => json({ usages: GRAMMAR });
  open();

  expect(
    await screen.findByRole("tab", { name: "문장 2", selected: true }),
  ).toBeInTheDocument();
  await items();
  expect(calls.map((c) => c.url)).not.toContain("/api/my-japanese/grammar/");

  await userEvent.click(screen.getByRole("tab", { name: "문법" }));

  expect(
    screen.getByRole("tab", { name: "문법", selected: true }),
  ).toBeVisible();
  const [first, second] = await grammarCards();
  expect(first).toHaveTextContent("ている");
  expect(first).toHaveTextContent("진행");
  expect(first).toHaveTextContent("~하고 있다");
  expect(first).toHaveTextContent("동작이 이어지고 있음을 나타낸다");
  expect(within(first).getByText("AI 생성·미검수")).toBeInTheDocument();
  expect(within(second).queryByText("AI 생성·미검수")).not.toBeInTheDocument();
  expect(screen.queryByRole("list", { name: "분석한 문장" })).toBeNull();
});

test("문법 카드에서 그 용법이 나온 내 문장으로 간다", async () => {
  responses["GET /api/my-japanese/grammar/"] = () => json({ usages: GRAMMAR });
  open();
  await userEvent.click(await screen.findByRole("tab", { name: "문법" }));
  const [first] = await grammarCards();

  expect(within(first).getByText("문장 2개")).toBeInTheDocument();
  expect(
    within(first).getByRole("link", { name: "私は学生です。" }),
  ).toHaveAttribute("href", "/sentences/1");
});

test("문법이 없으면 안내한다", async () => {
  responses["GET /api/my-japanese/grammar/"] = () => json({ usages: [] });
  open();
  await userEvent.click(await screen.findByRole("tab", { name: "문법" }));

  expect(
    await screen.findByText("분석한 문장에 나온 문법이 아직 없어요."),
  ).toBeInTheDocument();
});

test("문법을 불러오지 못하면 알린다", async () => {
  responses["GET /api/my-japanese/grammar/"] = () => json({}, 500);
  open();
  await userEvent.click(await screen.findByRole("tab", { name: "문법" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "문법을 불러오지 못했어요.",
  );
});

test("탭은 주소에 남아 뒤로 오면 그 탭을 다시 연다", async () => {
  responses["GET /api/my-japanese/grammar/"] = () => json({ usages: GRAMMAR });
  render(
    <MemoryRouter initialEntries={["/sentences?tab=grammar"]}>
      <Routes>
        <Route path="/sentences" element={<MySentencesPage />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(
    await screen.findByRole("tab", { name: "문법", selected: true }),
  ).toBeInTheDocument();
  expect(await grammarCards()).toHaveLength(2);
});

const WORDS = [
  {
    sense_id: 11,
    dictionary_form: "走る",
    reading: "はしる",
    tags: ["verb", "group1"],
    in_dictionary: true,
    sense: {
      tags: [],
      gloss_en: ["to run"],
      origin: "jmdict",
      status: "approved",
      meaning_ko: "달리다",
      meaning_status: "ai",
    },
    sentences: [
      { id: 2, text: "猫が好きです。" },
      { id: 1, text: "私は学生です。" },
    ],
  },
  {
    sense_id: 12,
    dictionary_form: "猫",
    reading: "ねこ",
    tags: ["noun"],
    in_dictionary: true,
    sense: {
      tags: [],
      gloss_en: ["cat"],
      origin: "jmdict",
      status: "approved",
      meaning_ko: "고양이",
      meaning_status: "reviewed",
    },
    sentences: [{ id: 2, text: "猫が好きです。" }],
  },
];

const wordRows = async () => {
  const list = await screen.findByRole("list", { name: "내 단어" });
  return within(list)
    .getAllByRole("listitem")
    .filter((li) => li.parentElement === list);
};

test("단어 탭은 열 때 불러와 뜻·태그·AI 번역 표시와 나온 문장을 보인다", async () => {
  responses["GET /api/my-japanese/words/"] = () => json({ words: WORDS });
  open();
  await items();
  expect(calls.map((c) => c.url)).not.toContain("/api/my-japanese/words/");

  await userEvent.click(screen.getByRole("tab", { name: "단어" }));

  const [run, cat] = await wordRows();
  expect(within(run).getByRole("heading", { name: "走る" })).toBeVisible();
  expect(run).toHaveTextContent("はしる");
  expect(run).toHaveTextContent("달리다");
  expect(within(run).getByText("1그룹")).toBeInTheDocument();
  expect(within(run).getByText("AI 번역")).toBeInTheDocument();
  expect(within(cat).queryByText("AI 번역")).not.toBeInTheDocument();
  expect(within(run).getByText("문장 2개")).toBeInTheDocument();
  expect(
    within(run).getByRole("link", { name: "私は学生です。" }),
  ).toHaveAttribute("href", "/sentences/1");
  const credit = screen.getByText(/내 문장에서 고른 뜻만/);
  expect(within(credit).getByRole("link", { name: "JMdict" })).toBeVisible();
});

test("단어가 없으면 안내한다", async () => {
  responses["GET /api/my-japanese/words/"] = () => json({ words: [] });
  open();
  await userEvent.click(await screen.findByRole("tab", { name: "단어" }));
  expect(
    await screen.findByText("분석한 문장에 나온 단어가 아직 없어요."),
  ).toBeInTheDocument();
});

test("단어를 불러오지 못하면 알린다", async () => {
  responses["GET /api/my-japanese/words/"] = () => json({}, 500);
  open();
  await userEvent.click(await screen.findByRole("tab", { name: "단어" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "단어를 불러오지 못했어요.",
  );
});
