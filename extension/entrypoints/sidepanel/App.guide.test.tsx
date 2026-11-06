import { describe, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { fireEvent, render, screen } from "@testing-library/react";
import App from "./App";
import "./app-test-support";

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

describe("가이드(#370)", () => {
  test("헤더 '?' 버튼은 가이드를 새 탭으로 연다", async () => {
    const create = vi.spyOn(fakeBrowser.tabs, "create");
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "가이드" }));

    expect(create).toHaveBeenCalledWith({
      url: fakeBrowser.runtime.getURL("/guide.html"),
    });
  });

  test("로그인 전 화면에도 '?' 버튼이 있다", async () => {
    await fakeBrowser.storage.local.clear();
    render(<App />);

    await screen.findByRole("heading", { name: "로그인이 필요해요" });
    expect(screen.getByRole("button", { name: "가이드" })).toBeInTheDocument();
  });
});
