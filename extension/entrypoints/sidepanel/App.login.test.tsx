import { describe, expect, test, vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { WEB_ORIGIN, handleExternalMessage } from "@/utils/external-messages";
import { loadToken, saveToken, signOut } from "@/utils/auth";
import { requestAnalysis } from "@/utils/analysis-request";
import {
  analysis,
  json,
  panelWindowId,
  respondWith,
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

describe("로그인과 확장 연결(#109)", () => {
  test("연결하지 않았으면 로그인 안내를 보이고, 버튼이 웹 연결 화면을 새 탭으로 연다", async () => {
    await fakeBrowser.storage.local.clear();
    const openTab = vi.spyOn(fakeBrowser.tabs, "create");
    render(<App />);

    const button = await screen.findByRole("button", {
      name: "로그인하고 연결하기",
    });
    expect(
      screen.getByRole("heading", { name: "로그인이 필요해요" }),
    ).toBeInTheDocument();
    fireEvent.click(button);

    expect(openTab).toHaveBeenCalledWith({ url: `${WEB_ORIGIN}/connect` });
  });

  test("헤더 로고는 웹 페이지로 가는 링크다", async () => {
    await fakeBrowser.storage.local.clear();
    render(<App />);

    const logo = await screen.findByRole("link", { name: "Dragram" });

    expect(logo).toHaveAttribute("href", `${WEB_ORIGIN}/`);
    expect(logo).toHaveAttribute("target", "_blank");
    expect(logo.querySelector("svg.logo-mark")).not.toBeNull();
  });

  test("분석 요청에 토큰을 Bearer로 붙인다", async () => {
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    render(<App />);

    await send(panelWindowId, "私は学生です。");

    expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
    const init = fetchMock.mock.calls[0]![1];
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer extension-token",
    );
  });

  test("서버가 로그인이 필요하다고 하면 토큰을 지우고 로그인 안내를 보인다", async () => {
    respondWith(401, { error: "AUTH:LOGIN_REQUIRED" });
    render(<App />);

    await send(panelWindowId, "私は学生です。");

    expect(
      await screen.findByRole("heading", { name: "로그인이 필요해요" }),
    ).toBeInTheDocument();
    expect(await loadToken()).toBeUndefined();
  });

  test("연결이 끝나면 안내를 닫고 기다리던 문장을 다시 분석한다", async () => {
    await fakeBrowser.storage.local.clear();
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    render(<App />);
    await send(panelWindowId, "私は学生です。");
    await screen.findByRole("heading", { name: "로그인이 필요해요" });
    expect(fetchMock).not.toHaveBeenCalled();

    await saveToken("new-token");

    expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "로그인이 필요해요" }),
    ).not.toBeInTheDocument();
  });

  test("로그아웃하면 서버에서 이 토큰을 폐기하고 로그인 안내를 보인다", async () => {
    const response = new Response(null, { status: 204 });
    const fetchMock = vi.fn().mockResolvedValue(response);
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "로그아웃" }));

    expect(
      await screen.findByRole("heading", { name: "로그인이 필요해요" }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]![0]).toMatch(
      /\/api\/auth\/extension-tokens\/revoke\/$/,
    );
    expect(fetchMock).toHaveReturnedTimes(1);
    await expect(fetchMock.mock.results[0]!.value).resolves.toMatchObject({
      status: 204,
      body: null,
    });
    expect(await loadToken()).toBeUndefined();
  });

  test("로그아웃하면 보던 원문과 결과를 지워, 다음에 연결한 사람에게 보이지 않는다", async () => {
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(
        url.endsWith("/revoke/")
          ? new Response(null, { status: 204 })
          : json(200, analysis("나는 학생입니다.")),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await send(panelWindowId, "私は学生です。");
    await screen.findByText("나는 학생입니다.");

    fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));
    await screen.findByRole("heading", { name: "로그인이 필요해요" });
    await saveToken("someone-else-token");

    await screen.findByRole("button", { name: "로그아웃" });
    expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
    expect(screen.queryByText("나는 학생입니다.")).not.toBeInTheDocument();
    // 다시 분석하지도 않는다.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("다시 연결한 뒤에 옛 토큰의 401이 와도 그 문장을 새 토큰으로 다시 분석한다", async () => {
    let rejectOld!: (response: Response) => void;
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      const auth = (init.headers as Record<string, string>).Authorization;
      if (auth === "Bearer extension-token") {
        return new Promise<Response>((resolve) => (rejectOld = resolve));
      }
      return Promise.resolve(json(200, analysis("나는 학생입니다.")));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await send(panelWindowId, "私は学生です。");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await saveToken("new-token");
    rejectOld(json(401, { error: "AUTH:LOGIN_REQUIRED" }));

    expect(await screen.findByText("나는 학생입니다.")).toBeInTheDocument();
    expect(await loadToken()).toBe("new-token");
  });

  test("웹에서 로그아웃해도 보던 원문과 결과를 지운다", async () => {
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    render(<App />);
    await send(panelWindowId, "私は学生です。");
    await screen.findByText("나는 학생입니다.");

    await handleExternalMessage(
      { type: "disconnect" },
      `${WEB_ORIGIN}/connect`,
    );
    await screen.findByRole("heading", { name: "로그인이 필요해요" });
    await saveToken("someone-else-token");

    await screen.findByRole("button", { name: "로그아웃" });
    expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("이미 지나간 회차의 401이 늦게 와도 지금 회차를 다시 보내지 않는다", async () => {
    let rejectOld!: (response: Response) => void;
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      const { text } = JSON.parse(init.body as string) as { text: string };
      if (text === "古い文です。") {
        return new Promise<Response>((resolve) => (rejectOld = resolve));
      }
      return Promise.resolve(json(200, analysis("새 문장")));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    await send(panelWindowId, "古い文です。");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    // 다시 연결하고 새 문장을 고른다.
    await saveToken("new-token");
    await send(panelWindowId, "新しい文です。");
    await screen.findByText("새 문장");

    rejectOld(json(401, { error: "AUTH:LOGIN_REQUIRED" }));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("새 문장")).toBeInTheDocument();
  });

  test("로그아웃 전에 들어와 남아 있던 분석 요청은 다음에 연결한 사람에게 분석하지 않는다", async () => {
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    // 패널이 닫힌 동안 들어온 요청이 세션 저장소에 남아 있다.
    await send(panelWindowId, "私は学生です。");
    await signOut();
    await saveToken("someone-else-token", "someone-else");

    render(<App />);
    await screen.findByRole("button", { name: "로그아웃" });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("로그아웃 전에 시작한 문장 추출이 늦게 저장돼도 버린다", async () => {
    const fetchMock = respondWith(200, analysis("나는 학생입니다."));
    render(<App />);
    await screen.findByRole("button", { name: "로그아웃" });
    const startedAt = Date.now() - 1000;
    await signOut();
    await saveToken("someone-else-token", "someone-else");

    await requestAnalysis(
      panelWindowId,
      [{ text: "私は学生です。" }],
      startedAt,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(screen.queryByText("私は学生です。")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
