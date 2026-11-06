import { expect, test, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import App from "./App";
import {
  approvedGrammarItem,
  grammarItem,
  panelWindowId,
  respondWith,
  send,
  streamed,
  withParts,
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

// 번역 아래 '선택한 카드' 박스(#354)
function selectedBox() {
  return screen.queryByRole("region", { name: "선택한 카드" });
}

test("원문 형광펜을 누르면 번역 아래 '선택한 카드'에 그 문법 카드를 보인다", async () => {
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
  await screen.findByRole("tab", { name: "문법 2" });
  expect(selectedBox()).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "です" }));

  const box = selectedBox()!;
  expect(within(box).getByRole("heading").textContent).toBe("정중 です");
  expect(within(box).getByText("정중 です 설명")).toBeInTheDocument();
  expect(within(box).getByText("AI 생성·미검수")).toBeInTheDocument();
  // 박스는 원문 카드 안, 번역 바로 다음이다.
  expect(screen.getByText("나는 학생입니다.").nextElementSibling).toBe(box);
  expect(screen.getByRole("button", { name: "です" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByRole("button", { name: "は" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
});

test("다른 형광펜을 누르면 그 카드로 바꾸고, 같은 형광펜이나 닫기를 누르면 닫는다", async () => {
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
  await screen.findByRole("tab", { name: "문법 2" });

  fireEvent.click(screen.getByRole("button", { name: "は" }));
  fireEvent.click(screen.getByRole("button", { name: "です" }));
  expect(within(selectedBox()!).getByRole("heading").textContent).toBe(
    "정중 です",
  );

  fireEvent.click(screen.getByRole("button", { name: "です" }));
  expect(selectedBox()).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "は" }));
  fireEvent.click(within(selectedBox()!).getByRole("button", { name: "닫기" }));
  expect(selectedBox()).toBeNull();
});

test("형광펜은 키보드로 가서 Enter·Space로 누를 수 있다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は", "は")],
    words: [],
  });
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  await screen.findByRole("tab", { name: "문법 1" });
  const mark = screen.getByRole("button", { name: "は" });
  expect(mark).toHaveAttribute("tabindex", "0");

  fireEvent.keyDown(mark, { key: "Enter" });
  expect(selectedBox()).not.toBeNull();

  fireEvent.keyDown(mark, { key: " " });
  expect(selectedBox()).toBeNull();
});

test("합친 카드의 어느 자리나 구성 문법 글자를 눌러도 그 카드 한 장을 연다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [
      grammarItem(1, 2, "주어 が", "が"),
      grammarItem(3, 4, "주어 が", "が"),
      withParts(
        grammarItem(6, 10, "완료", "てしまう"),
        grammarItem(6, 7, "연결", "て"),
      ),
    ],
    words: [],
  });
  render(<App />);
  await send(panelWindowId, "猫が犬が食べてしまう");
  await screen.findByRole("heading", { name: "완료" });
  const [, second] = screen.getAllByRole("button", { name: "が" });

  fireEvent.click(second!);

  expect(within(selectedBox()!).getAllByRole("heading")).toHaveLength(1);
  expect(within(selectedBox()!).getByRole("heading").textContent).toBe(
    "주어 が",
  );
  // 누른 자리만 눌린 상태다.
  expect(
    screen
      .getAllByRole("button", { name: "が" })
      .map((button) => button.getAttribute("aria-pressed")),
  ).toEqual(["false", "true"]);

  fireEvent.click(screen.getByRole("button", { name: "てしまう" }));

  const box = selectedBox()!;
  expect(within(box).getByRole("heading", { level: 3 }).textContent).toBe(
    "완료",
  );
  expect(
    within(within(box).getByRole("list", { name: "구성 문법" })).getByRole(
      "heading",
      { level: 4 },
    ).textContent,
  ).toBe("연결");
});

test("단어 출처 각주는 단어 목록과 '선택한 카드' 모두 출처만 보인다", async () => {
  respondWith(200, {
    translation_ko: "먹었다",
    grammar: [],
    words: [wordItem(0, 2, "食べる", "たべる")],
  });
  render(<App />);
  await send(panelWindowId, "食べた");
  fireEvent.click(await screen.findByRole("tab", { name: "단어 1" }));

  fireEvent.click(screen.getByRole("button", { name: "食べ" }));

  expect(within(selectedBox()!).getByText(/단어 정보/).textContent).toBe(
    "단어 정보: JMdict (EDRDG, CC BY-SA 4.0)",
  );
  expect(
    within(screen.getByRole("tabpanel")).getByText(/단어 정보/).textContent,
  ).toBe("단어 정보: JMdict (EDRDG, CC BY-SA 4.0)");
});

test("원문의 단어를 누르면 '선택한 카드'에 그 글자의 문법 카드와 그 아래 단어 카드를 보인다", async () => {
  respondWith(200, {
    translation_ko: "먹어 버렸다",
    grammar: [grammarItem(2, 6, "완료", "てしまう")],
    words: [
      wordItem(0, 2, "食べる", "たべる"),
      wordItem(3, 6, "しまう", "しまう"),
    ],
  });
  render(<App />);
  await send(panelWindowId, "食べてしまった");
  await screen.findByRole("tab", { name: "문법 1" });
  const headings = () =>
    within(selectedBox()!)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
  // 형광펜은 단어 경계에서 쪼개지 않는다.
  expect(
    [...document.querySelectorAll(".original mark")].map(
      (mark) => mark.textContent,
    ),
  ).toEqual(["てしまっ"]);

  fireEvent.click(screen.getByRole("button", { name: "しまっ" }));
  expect(headings()).toEqual(["완료", "しまう"]);

  // 형광펜이 없는 단어는 단어 카드만 보인다.
  fireEvent.click(screen.getByRole("button", { name: "食べ" }));
  expect(headings()).toEqual(["食べる"]);

  // 단어가 없는 형광펜 글자는 문법 카드만 보인다.
  fireEvent.click(screen.getByRole("button", { name: "て" }));
  expect(headings()).toEqual(["완료"]);
});

test("보통 카드끼리 겹친 글자를 누르면 먼저 시작한 문법의 카드를 연다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [grammarItem(1, 4, "앞 문법"), grammarItem(2, 5, "뒤 문법")],
    words: [],
  });
  render(<App />);
  await send(panelWindowId, "一二三四五六");
  await screen.findByRole("tab", { name: "문법 2" });

  fireEvent.click(screen.getByRole("button", { name: "三四" }));
  expect(within(selectedBox()!).getByRole("heading").textContent).toBe(
    "앞 문법",
  );

  fireEvent.click(screen.getByRole("button", { name: "五" }));
  expect(within(selectedBox()!).getByRole("heading").textContent).toBe(
    "뒤 문법",
  );
});

test("먼저 온 문법 형광펜도 누를 수 있고, 분석 결과에서 그 카드가 사라지면 닫는다", async () => {
  const stream = streamed();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream.response));
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  stream.push({
    type: "grammar",
    grammar: [
      approvedGrammarItem(1, 2, "주제 は"),
      approvedGrammarItem(4, 6, "정중 です"),
    ],
  });
  fireEvent.click(await screen.findByRole("button", { name: "は" }));
  expect(within(selectedBox()!).getByRole("heading").textContent).toBe(
    "주제 は",
  );

  stream.push({
    type: "translation",
    translation_ko: "나는 학생입니다.",
    ruby: [],
  });
  stream.push({
    type: "analysis",
    translation_ko: "나는 학생입니다.",
    grammar: [approvedGrammarItem(4, 6, "정중 です")],
    words: [],
  });
  stream.end();

  await screen.findByRole("tab", { name: "문법 1" });
  expect(selectedBox()).toBeNull();
});

test("다른 문장 페이지로 넘기면 '선택한 카드'를 닫는다", async () => {
  respondWith(200, {
    translation_ko: "번역",
    grammar: [grammarItem(1, 2, "주제 は", "は")],
    words: [],
  });
  render(<App />);
  await send(panelWindowId, "私は学生。", "彼は先生。");
  await screen.findByRole("heading", { name: "주제 は" });
  fireEvent.click(screen.getByRole("button", { name: "は" }));
  expect(selectedBox()).not.toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "다음 문장" }));
  await screen.findByText("2 / 2");

  expect(selectedBox()).toBeNull();
});
