import { render, screen } from "@testing-library/react";
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

beforeEach(() => {
  fakeBrowser.reset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("사이드 패널에 앱 이름을 제목으로 보여준다", () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "Dragram" })).toBeInTheDocument();
});

test("분석 요청을 받으면 원문을 보이고, 응답 전에는 번역 자리에 스켈레톤을 보인다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
  render(<App />);

  await requestAnalysis("私は学生です。");

  expect(await screen.findByText("私は学生です。")).toBeInTheDocument();
  expect(
    screen.getByRole("status", { name: "번역을 불러오는 중" }),
  ).toBeInTheDocument();
});

test("응답이 오면 번역을 보인다", async () => {
  const fetchMock = respondWith(200, { translation_ko: "나는 학생입니다." });
  render(<App />);

  await requestAnalysis("私は学生です。");

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
  expect(
    screen.queryByRole("status", { name: "번역을 불러오는 중" }),
  ).not.toBeInTheDocument();
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toMatch(/\/api\/analyses\/$/);
  expect(JSON.parse(init.body)).toEqual({ text: "私は学生です。" });
});

test("패널이 열리기 전에 들어온 분석 요청도 보인다", async () => {
  respondWith(200, { translation_ko: "나는 학생입니다." });
  await requestAnalysis("私は学生です。");

  render(<App />);

  expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
});

test("실패 응답이면 '분석하지 못했습니다'를 보인다", async () => {
  respondWith(502, { error: "analysis_failed" });
  render(<App />);

  await requestAnalysis("私は学生です。");

  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();
});

test("서버에 연결하지 못하면 '분석하지 못했습니다'를 보인다", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
  );
  render(<App />);

  await requestAnalysis("私は学生です。");

  expect(await screen.findByText("분석하지 못했습니다")).toBeInTheDocument();
});
