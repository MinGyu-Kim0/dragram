import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { sentencesFromPage } from "./page-sentences";

beforeEach(() => {
  fakeBrowser.reset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const extracted = [
  { text: "私は学生です。", selection: { start: 2, end: 4 } },
  { text: "猫です。", selection: { start: 0, end: 1 } },
];

test("고른 글이 있던 탭·프레임에 추출 스크립트를 주입해 문장 목록을 받는다", async () => {
  const executeScript = vi
    .spyOn(fakeBrowser.scripting, "executeScript")
    // executeScript는 콜백형 오버로드 때문에 반환 타입이 void로 잡혀 결과를 never로 넘긴다.
    .mockResolvedValue([
      { frameId: 3, documentId: "d", result: extracted },
    ] as never);

  const sentences = await sentencesFromPage(7, 3, "学生です。猫");

  expect(sentences).toEqual(extracted);
  expect(executeScript).toHaveBeenCalledWith({
    target: { tabId: 7, frameIds: [3] },
    files: ["/extract-sentences.js"],
  });
});

test("주입할 수 없는 페이지면 고른 글자를 문장 하나로 보낸다", async () => {
  // 크롬 내부 페이지, 웹 스토어, PDF 뷰어 등
  vi.spyOn(fakeBrowser.scripting, "executeScript").mockRejectedValue(
    new Error("Cannot access contents of the page"),
  );

  expect(await sentencesFromPage(7, 0, "学生")).toEqual([
    { text: "学生", selection: { start: 0, end: 2 } },
  ]);
});

test("문장을 찾지 못하면 고른 글자를 문장 하나로 보낸다", async () => {
  vi.spyOn(fakeBrowser.scripting, "executeScript").mockResolvedValue([
    { frameId: 0, documentId: "d", result: [] },
  ] as never);

  expect(await sentencesFromPage(7, 0, "学生")).toEqual([
    { text: "学生", selection: { start: 0, end: 2 } },
  ]);
});
