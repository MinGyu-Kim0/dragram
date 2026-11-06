import { describe, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { loadToken } from "@/utils/auth";
import {
  json,
  panelWindowId,
  respondPerSentence,
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

describe("확장 업데이트가 필요하면(#349)", () => {
  // requestUpdateCheck는 콜백 겹지정(void)이 있어 spyOn의 타입이 맞지 않는다. 직접 바꾼다.
  function updateCheck(result: () => Promise<unknown>) {
    const check = vi.fn(result);
    fakeBrowser.runtime.requestUpdateCheck = check as never;
    return check;
  }

  function refuseOldExtension() {
    respondPerSentence({
      "私は学生です。": () => json(426, { error: "EXTENSION:UPDATE_REQUIRED" }),
    });
  }

  test("업데이트 안내를 보이고 확장 연결은 지우지 않는다", async () => {
    refuseOldExtension();
    render(<App />);

    await send(panelWindowId, "私は学生です。");

    expect(
      await screen.findByRole("heading", { name: "업데이트가 필요해요" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "지금 업데이트" }),
    ).toBeInTheDocument();
    expect(await loadToken()).toBe("extension-token");
    expect(screen.queryByText("분석하지 못했습니다")).not.toBeInTheDocument();
  });

  test("지금 업데이트를 누르면 업데이트를 받아 확장을 다시 띄운다", async () => {
    refuseOldExtension();
    const check = updateCheck(async () => ({
      status: "update_available",
      version: "0.4.0",
    }));
    const reload = vi
      .spyOn(fakeBrowser.runtime, "reload")
      .mockImplementation(() => {});
    render(<App />);
    await send(panelWindowId, "私は学生です。");

    fireEvent.click(
      await screen.findByRole("button", { name: "지금 업데이트" }),
    );

    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(check).toHaveBeenCalled();
  });

  test.each([
    { status: "no_update" },
    { status: "throttled" },
    new Error("확인 실패"),
  ])(
    "업데이트를 받을 수 없으면(%o) 잠시 뒤 다시 해 보라고 한다",
    async (result) => {
      refuseOldExtension();
      updateCheck(async () => {
        if (result instanceof Error) throw result;
        return result;
      });
      const reload = vi.spyOn(fakeBrowser.runtime, "reload");
      render(<App />);
      await send(panelWindowId, "私は学生です。");

      fireEvent.click(
        await screen.findByRole("button", { name: "지금 업데이트" }),
      );

      expect(
        await screen.findByText(
          "아직 받을 수 있는 업데이트가 없어요. 잠시 뒤 다시 해 주세요.",
        ),
      ).toBeInTheDocument();
      expect(reload).not.toHaveBeenCalled();
    },
  );
});
