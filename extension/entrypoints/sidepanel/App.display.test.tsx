import { expect, test, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import App from "./App";
import { fakeBrowser } from "wxt/testing/fake-browser";
import {
  grammarItem,
  panelWindowId,
  respondWith,
  rubies,
  rubyItem,
  send,
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

/** 브라우저 설정(prefers-color-scheme)을 흉내 낸다. 돌려준 함수로 설정을 바꾼다. */
function prefersDark(dark: boolean) {
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      return dark && query === "(prefers-color-scheme: dark)";
    },
    addEventListener: (_: string, listener: () => void) =>
      listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) =>
      listeners.delete(listener),
  }));
  return (next: boolean) => {
    dark = next;
    listeners.forEach((listener) => listener());
  };
}

test("고른 적이 없으면 브라우저 설정이 바뀔 때 테마 버튼도 따라 바뀐다", async () => {
  const setDark = prefersDark(false);
  render(<App />);
  const button = await screen.findByRole("button", { name: "다크 모드" });
  expect(button).toHaveAttribute("aria-pressed", "false");

  act(() => setDark(true));
  expect(button).toHaveAttribute("aria-pressed", "true");
});

test("테마 버튼은 처음에는 브라우저 설정을 따르고 고른 테마를 고정하지 않는다", async () => {
  prefersDark(true);
  render(<App />);

  expect(
    await screen.findByRole("button", { name: "다크 모드" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(document.documentElement.dataset.theme).toBeUndefined();
});

test("테마 버튼을 누르면 반대 테마로 바뀌고 패널을 다시 열어도 유지된다", async () => {
  prefersDark(false);
  const { unmount } = render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "다크 모드" }));
  expect(document.documentElement.dataset.theme).toBe("dark");

  unmount();
  delete document.documentElement.dataset.theme;
  render(<App />);
  await waitFor(() =>
    expect(document.documentElement.dataset.theme).toBe("dark"),
  );
  expect(screen.getByRole("button", { name: "다크 모드" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("로그인 전 화면에도 테마 버튼이 있다", async () => {
  await fakeBrowser.storage.local.clear();
  render(<App />);

  await screen.findByRole("heading", { name: "로그인이 필요해요" });
  expect(screen.getByRole("button", { name: "다크 모드" })).toBeInTheDocument();
});

test("사이드 패널에 앱 이름을 제목으로 보여준다", () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "Dragram" })).toBeInTheDocument();
});

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
  expect(screen.getByRole("button", { name: "후리가나" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // 형광펜 안에도 루비를 단다.
  expect(document.querySelector(".original mark ruby")).not.toBeNull();
});

test("후리가나 버튼을 끄면 루비가 사라지고, 끈 값은 패널을 다시 열어도 유지된다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [],
    words: [],
    ruby: [rubyItem(0, 1, "わたし")],
  });
  const { unmount } = render(<App />);
  await send(panelWindowId, "私は学生です。");
  await screen.findByText("나는 학생입니다.");

  fireEvent.click(screen.getByRole("button", { name: "후리가나" }));

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

test("형광펜 모양을 '형광펜'과 '밑줄' 중에서 고르고, 고른 값은 패널을 다시 열어도 유지된다", async () => {
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は", "は")],
    words: [],
  });
  const { unmount } = render(<App />);
  await send(panelWindowId, "私は学生です。");
  await screen.findByText("나는 학생입니다.");
  const style = () =>
    within(screen.getByRole("group", { name: "형광펜 모양" }));
  const original = () => document.querySelector(".original")!;
  // 기본은 형광펜이고, 드래그 표시 버튼은 없다(#354).
  expect(style().getByRole("button", { name: "형광펜" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(original()).not.toHaveClass("underline");
  expect(
    screen.queryByRole("button", { name: "드래그 표시" }),
  ).not.toBeInTheDocument();

  fireEvent.click(style().getByRole("button", { name: "밑줄" }));

  expect(style().getByRole("button", { name: "밑줄" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(style().getByRole("button", { name: "형광펜" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  expect(original()).toHaveClass("underline");

  unmount();
  respondWith(200, {
    translation_ko: "나는 학생입니다.",
    grammar: [grammarItem(1, 2, "주제 は", "は")],
    words: [],
  });
  render(<App />);
  await send(panelWindowId, "私は学生です。");
  await screen.findByText("나는 학생입니다.");
  await waitFor(() => expect(original()).toHaveClass("underline"));
});
