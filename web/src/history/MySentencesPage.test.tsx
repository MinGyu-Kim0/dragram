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
