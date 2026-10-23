import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import ConnectPage from "./ConnectPage";

type Call = {
  url: string;
  method: string;
  headers: Record<string, string>;
  body?: string;
};

let calls: Call[];
let responses: Record<string, () => Response>;
let googleCallback: ((response: { credential: string }) => void) | undefined;
const renderButton = vi.fn();

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  calls = [];
  document.cookie = "csrftoken=csrf-value";
  responses = { "GET /api/auth/me/": () => json({ user: null }) };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({
        url,
        method,
        headers: (init.headers ?? {}) as Record<string, string>,
        body: init.body as string | undefined,
      });
      return responses[`${method} ${url}`]();
    }),
  );
  vi.stubGlobal("google", {
    accounts: {
      id: {
        initialize: (config: {
          callback: (r: { credential: string }) => void;
        }) => {
          googleCallback = config.callback;
        },
        renderButton,
      },
    },
  });
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "web-client-id");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  renderButton.mockClear();
});

test("로그인 전에는 Google 로그인 버튼을 보인다", async () => {
  render(<ConnectPage />);

  expect(
    await screen.findByRole("heading", { name: "Dragram에 로그인" }),
  ).toBeInTheDocument();
  // 버튼은 Google 스크립트를 불러온 뒤에 그린다.
  await waitFor(() => expect(renderButton).toHaveBeenCalledTimes(1));
  expect(
    screen.queryByRole("button", { name: "로그아웃" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("Google이 준 ID 토큰을 CSRF 값과 함께 보내고 로그인한 계정을 보인다", async () => {
  responses["POST /api/auth/google/"] = () =>
    json({ user: { email: "me@example.com" } });
  render(<ConnectPage />);
  await screen.findByRole("heading", { name: "Dragram에 로그인" });

  await act(async () => googleCallback!({ credential: "google-id-token" }));

  expect(await screen.findByText("me@example.com")).toBeInTheDocument();
  const login = calls.find((c) => c.url === "/api/auth/google/")!;
  expect(login.method).toBe("POST");
  expect(login.headers["X-CSRFToken"]).toBe("csrf-value");
  expect(JSON.parse(login.body!)).toEqual({ credential: "google-id-token" });
});

test("로그인한 상태면 이메일과 로그아웃을 보이고, 로그아웃하면 로그인 버튼으로 돌아간다", async () => {
  responses["GET /api/auth/me/"] = () =>
    json({ user: { email: "me@example.com" } });
  responses["POST /api/auth/logout/"] = () => json({ user: null });
  render(<ConnectPage />);

  expect(await screen.findByText("me@example.com")).toBeInTheDocument();
  expect(renderButton).not.toHaveBeenCalled();

  await userEvent.click(screen.getByRole("button", { name: "로그아웃" }));

  expect(
    await screen.findByRole("heading", { name: "Dragram에 로그인" }),
  ).toBeInTheDocument();
  const logout = calls.find((c) => c.url === "/api/auth/logout/")!;
  expect(logout.headers["X-CSRFToken"]).toBe("csrf-value");
});

test("로그인이 거부되면 다시 시도하라고 안내한다", async () => {
  responses["POST /api/auth/google/"] = () =>
    json({ error: "AUTH:EMAIL_NOT_VERIFIED" }, 403);
  render(<ConnectPage />);
  await screen.findByRole("heading", { name: "Dragram에 로그인" });

  await act(async () => googleCallback!({ credential: "google-id-token" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "로그인하지 못했어요",
  );
});

test("Google 버튼을 준비하지 못하면 로그인 실패와 다르게 안내한다", async () => {
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "");
  render(<ConnectPage />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "로그인 버튼을 불러오지 못했어요",
  );
  expect(renderButton).not.toHaveBeenCalled();
});

test("로그아웃이 실패하면 로그인한 상태를 그대로 보이고 안내한다", async () => {
  responses["GET /api/auth/me/"] = () =>
    json({ user: { email: "me@example.com" } });
  responses["POST /api/auth/logout/"] = () =>
    json({ error: "AUTH:CSRF_FAILED" }, 403);
  render(<ConnectPage />);
  await screen.findByText("me@example.com");

  await userEvent.click(screen.getByRole("button", { name: "로그아웃" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "로그아웃하지 못했어요",
  );
  expect(screen.getByText("me@example.com")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "로그아웃" })).toBeInTheDocument();
});

describe("확장 연결(#109)", () => {
  type Message = { type: string; token?: string };
  let sent: { extensionId: string; message: Message }[];
  let reply: { ok: boolean } | undefined;
  let lastError: { message: string } | undefined;

  beforeEach(() => {
    sent = [];
    reply = { ok: true };
    lastError = undefined;
    responses["GET /api/auth/me/"] = () =>
      json({ user: { email: "me@example.com" } });
    responses["POST /api/auth/extension-tokens/"] = () =>
      json({ token: "extension-token" }, 201);
    vi.stubEnv("VITE_EXTENSION_ID", "dragram-extension-id");
    const runtime = {
      get lastError() {
        return lastError;
      },
      sendMessage: (
        extensionId: string,
        message: Message,
        callback: (response?: { ok: boolean }) => void,
      ) => {
        sent.push({ extensionId, message });
        callback(reply);
      },
    };
    vi.stubGlobal("chrome", { runtime });
  });

  test("확장 연결을 누르면 토큰을 받아 확장에 넘기고 연결 성공 카드를 보인다", async () => {
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );

    expect(
      await screen.findByRole("heading", { name: "연결했어요" }),
    ).toBeInTheDocument();
    const issue = calls.find((c) => c.url === "/api/auth/extension-tokens/")!;
    expect(issue.method).toBe("POST");
    expect(issue.headers["X-CSRFToken"]).toBe("csrf-value");
    expect(sent).toEqual([
      {
        extensionId: "dragram-extension-id",
        message: { type: "connect", token: "extension-token" },
      },
    ]);
  });

  test("확장이 응답하지 않으면 설치를 확인하라고 안내한다", async () => {
    reply = undefined;
    lastError = { message: "Could not establish connection." };
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "확장 프로그램을 찾지 못했어요",
    );
    expect(
      screen.queryByRole("heading", { name: "연결했어요" }),
    ).not.toBeInTheDocument();
  });

  test("브라우저에 확장 연결 기능이 없어도 같은 안내를 보인다", async () => {
    vi.stubGlobal("chrome", undefined);
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "확장 프로그램을 찾지 못했어요",
    );
  });

  test("웹에서 로그아웃하면 확장에도 연결을 끊으라고 알린다", async () => {
    responses["POST /api/auth/logout/"] = () => json({ user: null });
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "로그아웃" }),
    );

    await screen.findByRole("heading", { name: "Dragram에 로그인" });
    expect(sent).toEqual([
      { extensionId: "dragram-extension-id", message: { type: "disconnect" } },
    ]);
  });

  test("연결하는 동안에는 로그아웃할 수 없어, 폐기된 토큰을 확장에 넘기지 않는다", async () => {
    let finishIssue!: () => void;
    responses["POST /api/auth/extension-tokens/"] = () =>
      json({ token: "extension-token" }, 201);
    const issued = new Promise<void>((resolve) => (finishIssue = resolve));
    const original = globalThis.fetch;
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url === "/api/auth/extension-tokens/") await issued;
      return original(url, init);
    });
    render(<ConnectPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "확장 프로그램 연결" }),
    );

    expect(screen.getByRole("button", { name: "로그아웃" })).toBeDisabled();
    finishIssue();
    expect(
      await screen.findByRole("heading", { name: "연결했어요" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "로그아웃" })).toBeEnabled();
  });
});
